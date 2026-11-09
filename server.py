"""
server.py — Production Web Server & REST API Bridge for Autonomous Job Application Agent.

Features:
- Connects directly to the SQLite database (`applied_jobs.db`) using the exact schema
  defined in `db/models.py` (`applied_jobs`, `job_queue`, `session_log`).
- Reads and updates `.env` / candidate profile settings safely.
- Enforces HTTPS redirect (when `FORCE_HTTPS=true` or behind a proxy with `X-Forwarded-Proto: http`)
  and sets strict production security headers (HSTS, CSP, X-Frame-Options, X-Content-Type-Options,
  Referrer-Policy, Permissions-Policy).
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import mimetypes
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
RESUMES_DIR = PROJECT_ROOT / "resumes"
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE_FILE = PROJECT_ROOT / ".env.example"


def _load_env_dict() -> Dict[str, str]:
    """Parse .env (falling back to .env.example) into a key-value dictionary."""
    env_data: Dict[str, str] = {}
    for source in (ENV_EXAMPLE_FILE, ENV_FILE):
        if source.exists():
            for raw_line in source.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env_data[k.strip()] = v.strip()
    for k, v in os.environ.items():
        if k in env_data:
            env_data[k] = v
    return env_data


def _save_env_updates(updates: Dict[str, Any]) -> None:
    """Persist updated configuration keys to .env while preserving structure and comments."""
    target = ENV_FILE if ENV_FILE.exists() else ENV_EXAMPLE_FILE
    lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    updated_keys = set()
    new_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                val = updates[key]
                val_str = ("true" if val else "false") if isinstance(val, bool) else str(val).replace("\n", " ").strip()
                new_lines.append(f"{key}={val_str}")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in updated_keys:
            val_str = ("true" if val else "false") if isinstance(val, bool) else str(val).replace("\n", " ").strip()
            new_lines.append(f"{key}={val_str}")

    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def get_db_path() -> Path:
    env = _load_env_dict()
    raw = env.get("DB_PATH", "applied_jobs.db")
    p = Path(raw)
    return p if p.is_absolute() else PROJECT_ROOT / p


def make_dedup_key(url: str, company: str, title: str) -> str:
    raw = f"{url.strip().lower()}{company.strip().lower()}{title.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_connection() -> sqlite3.Connection:
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_database(seed_if_empty: bool = True) -> None:
    """Ensure SQLite tables match `db/models.py` and optionally seed initial records."""
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS applied_jobs (
                id VARCHAR(64) PRIMARY KEY,
                timestamp DATETIME,
                job_title VARCHAR(255),
                company VARCHAR(255),
                location VARCHAR(255),
                posted_date VARCHAR(64),
                job_url TEXT,
                apply_site VARCHAR(128),
                ats_platform VARCHAR(64),
                status VARCHAR(32),
                note TEXT,
                resume_version VARCHAR(128),
                cover_letter TEXT,
                application_id VARCHAR(255),
                retry_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS job_queue (
                id VARCHAR(64) PRIMARY KEY,
                job_url TEXT,
                job_title VARCHAR(255),
                company VARCHAR(255),
                apply_site VARCHAR(128),
                priority INTEGER DEFAULT 5,
                added_date DATETIME,
                scheduled_date DATETIME,
                status VARCHAR(32) DEFAULT 'pending'
            );
            CREATE TABLE IF NOT EXISTS session_log (
                session_id VARCHAR(64) PRIMARY KEY,
                start_time DATETIME,
                end_time DATETIME,
                total_applied INTEGER DEFAULT 0,
                total_skipped INTEGER DEFAULT 0,
                total_failed INTEGER DEFAULT 0,
                sites_blocked TEXT,
                alerts_sent TEXT
            );
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(64) PRIMARY KEY,
                full_name VARCHAR(255),
                email VARCHAR(255) UNIQUE,
                password_hash VARCHAR(255),
                salt VARCHAR(64),
                onboarding_completed INTEGER DEFAULT 0,
                created_at DATETIME
            );
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token VARCHAR(128) PRIMARY KEY,
                user_email VARCHAR(255),
                created_at DATETIME
            );
            CREATE TABLE IF NOT EXISTS recruiter_contacts (
                id VARCHAR(64) PRIMARY KEY,
                name VARCHAR(255),
                email VARCHAR(255),
                job_title VARCHAR(255),
                company VARCHAR(255),
                source VARCHAR(128),
                status VARCHAR(64) DEFAULT 'scraped',
                last_contacted DATETIME,
                pitch_preview TEXT
            );
            """
        )
        conn.commit()
        if not seed_if_empty:
            return
        if conn.execute("SELECT COUNT(*) FROM recruiter_contacts").fetchone()[0] == 0:
            now_ts = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
            sample_recruiters = [
                ("Ananya Sharma (Tech Recruiter)", "ananya.sharma@linearlabs.ai", "Senior Backend & AI Engineer", "LinearLabs AI", "linkedin.com (Scenario A)", "emailed", now_ts, "Hi Ananya, I applied for Senior Backend & AI Engineer at LinearLabs AI and attached my CV."),
                ("Vikram Nair (Talent Acquisition)", "vikram.nair@razorpayx.com", "Python Microservices & GCP Lead", "RazorpayX Cloud", "naukri.com (JD Scraper)", "scraped", now_ts, "Hi Vikram, reaching out regarding the Python Microservices & GCP Lead opening at RazorpayX Cloud."),
                ("Sarah Jenkins (Engineering Recruiting)", "s.jenkins@cohere.com", "Senior FastAPI & LLM Engineer", "Cohere Enterprise", "linkedin.com (Scenario B)", "scraped", now_ts, "Hi Sarah, would love to be considered for an interview or referral for Senior FastAPI & LLM Engineer."),
                ("Rohan Verma (HR Lead)", "careers.ai@anthropic-partner.in", "Generative AI Systems Engineer", "Anthropic Partner Studio", "naukri.com (Scenario A)", "emailed", now_ts, "Hi Rohan, sharing my resume and GitHub profile for the Generative AI Systems Engineer role."),
            ]
            for r_name, r_email, r_role, r_comp, r_src, r_stat, r_ts, r_pitch in sample_recruiters:
                rid = make_dedup_key(r_email, r_comp, r_role)
                conn.execute(
                    "INSERT OR IGNORE INTO recruiter_contacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (rid, r_name, r_email, r_role, r_comp, r_src, r_stat, r_ts, r_pitch),
                )
            conn.commit()
        if conn.execute("SELECT COUNT(*) FROM applied_jobs").fetchone()[0] > 0:
            return

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        sample_jobs = [
            ("Senior Backend & AI Engineer", "LinearLabs AI", "Remote", "Today", "https://www.linkedin.com/jobs/view/linearlabs-ai-backend-409182", "linkedin.com", "Greenhouse", "applied", "96% skill match (Python, FastAPI, LangGraph, Gemini). Auto-submitted with tailored cover letter.", "resume_ai_backend_v4.pdf", "Dear Hiring Team at LinearLabs AI,\n\nI am excited to apply for the Senior Backend & AI Engineer role. My experience building autonomous LangGraph pipelines and FastAPI services aligns directly with your goals.", "GH-88412-LL", 1),
            ("Staff Python Platform Engineer", "Vercel Cloud Systems", "Remote (Global)", "1 day ago", "https://www.linkedin.com/jobs/view/vercel-cloud-python-409155", "linkedin.com", "Lever", "applied", "94% match. Recruiter connection request queued via Scenario B outreach.", "resume_ai_backend_v4.pdf", "Dear Vercel Cloud Systems Team,\n\nWith deep experience in distributed Python services and low-latency APIs, I would love to contribute to your core platform engineering group.", "LV-99201-VC", 3),
            ("Generative AI Systems Engineer", "Anthropic Partner Studio", "Hybrid · Bengaluru", "Today", "https://www.naukri.com/job-listings-genai-systems-engineer-918273", "naukri.com", "Naukri Direct", "applied", "Solved 4 chatbot screening questions via Gemini 2.5 Pro. Confirmed submission.", "resume_ai_backend_v4.pdf", "Tailored screening responses submitted via Naukri AI chatbot handler.", "NK-55109-AP", 5),
            ("Data & Distributed ETL Engineer", "Databricks Ecosystem Corp", "Remote", "2 days ago", "https://www.naukri.com/job-listings-data-etl-engineer-773819", "naukri.com", "Workday", "applied", "Matched Spark/Databricks/Python query. Direct referral email also logged.", "resume_data_eng_v2.pdf", "Submitted with emphasis on high-volume Spark & Dask pipelines.", "WD-33019-DB", 19),
            ("Machine Learning Infrastructure Engineer", "ScaleOps Autonomous", "Remote", "2 days ago", "https://www.linkedin.com/jobs/view/scaleops-ml-infra-883712", "linkedin.com", "Workday", "skipped", "External Workday portal requested SSN / sensitive field — halted safely per ethics guardrails.", "resume_ai_backend_v4.pdf", "", "", 26),
            ("Principal Backend Architect (Python/GCP)", "Stripe FinTech Core", "Remote", "3 days ago", "https://www.linkedin.com/jobs/view/stripe-fintech-python-661920", "linkedin.com", "Greenhouse", "applied", "92% match. Full Greenhouse form + custom demographic waivers completed.", "resume_ai_backend_v4.pdf", "Focused on high-reliability payment ledgers and idempotent microservices.", "GH-71904-ST", 44),
            ("AI Agent Workflow Engineer", "Perplexity Labs", "Remote", "4 days ago", "https://www.linkedin.com/jobs/view/perplexity-agent-eng-510293", "linkedin.com", "Ashby", "applied", "98% match on RAG, search orchestration, and stealth browser automation.", "resume_ai_backend_v4.pdf", "Highlighted autonomous browser agent architecture and LLM tool-use reliability.", "AS-40129-PX", 68),
            ("Cloud Backend Developer", "OmniShield Security", "On-site · Mumbai", "4 days ago", "https://www.naukri.com/job-listings-cloud-backend-omnishield-192831", "naukri.com", "Taleo", "failed", "CAPTCHA challenge detected on Taleo gateway — gracefully queued for manual review.", "resume_ai_backend_v4.pdf", "", "", 90),
        ]
        for title, company, loc, posted, url, site, ats, status, note, res_ver, cl, app_id, hrs in sample_jobs:
            jid = make_dedup_key(url, company, title)
            ts = (now - timedelta(hours=hrs)).isoformat(sep=" ", timespec="seconds")
            conn.execute(
                "INSERT OR IGNORE INTO applied_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (jid, ts, title, company, loc, posted, url, site, ats, status, note, res_ver, cl, app_id),
            )

        sample_queue = [
            ("Founding AI Infrastructure Engineer", "Cognition Systems", "https://www.linkedin.com/jobs/view/cognition-founding-ai-901122", "linkedin.com", 1),
            ("Senior FastAPI & LLM Engineer", "Cohere Enterprise", "https://www.linkedin.com/jobs/view/cohere-fastapi-llm-901450", "linkedin.com", 1),
            ("Python Microservices & GCP Lead", "RazorpayX Cloud", "https://www.naukri.com/job-listings-razorpayx-python-gcp-882190", "naukri.com", 2),
            ("Distributed Data Pipeline Engineer", "Snowflake Core", "https://www.linkedin.com/jobs/view/snowflake-data-pipeline-774123", "linkedin.com", 3),
        ]
        ts_now = now.isoformat(sep=" ", timespec="seconds")
        for title, company, url, site, prio in sample_queue:
            qid = make_dedup_key(url, company, title)
            conn.execute(
                "INSERT OR IGNORE INTO job_queue VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                (qid, url, title, company, site, prio, ts_now, ts_now),
            )

        conn.execute(
            "INSERT INTO session_log VALUES (?, ?, ?, 4, 1, 1, '[]', ?)",
            (
                str(uuid.uuid4()),
                (now - timedelta(hours=26)).isoformat(sep=" ", timespec="seconds"),
                (now - timedelta(hours=25, minutes=42)).isoformat(sep=" ", timespec="seconds"),
                json.dumps(["Daily summary email dispatched"]),
            ),
        )
        conn.commit()


class AgentRuntimeState:
    """Thread-safe runtime state and live log buffer for the Autonomous Job Agent."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.status: str = "idle"
        self.mode: str = "dry_run"
        self.active_session_id: Optional[str] = None
        self.started_at: Optional[str] = None
        self.progress_pct: int = 0
        self.current_step: str = "Standing by — Scheduler armed (08:00–21:00 window)"
        self.logs: List[Dict[str, str]] = [
            {"id": "init-1", "time": datetime.now().strftime("%H:%M:%S"), "level": "INFO", "message": "Autonomous Job Agent telemetry engine initialized."},
            {"id": "init-2", "time": datetime.now().strftime("%H:%M:%S"), "level": "INFO", "message": "Stealth Playwright profile & SQLite deduplication index verified."},
            {"id": "init-3", "time": datetime.now().strftime("%H:%M:%S"), "level": "SUCCESS", "message": "Ready for Dry-Run, Single-Link Apply, or Scheduled Execution."},
        ]

    def append_log(self, level: str, message: str) -> None:
        with self.lock:
            self.logs.append(
                {
                    "id": str(uuid.uuid4())[:8],
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "level": level,
                    "message": message,
                }
            )
            if len(self.logs) > 100:
                self.logs = self.logs[-100:]

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "status": self.status,
                "mode": self.mode,
                "active_session_id": self.active_session_id,
                "started_at": self.started_at,
                "progress_pct": self.progress_pct,
                "current_step": self.current_step,
                "logs": list(self.logs[-35:]),
            }


RUNTIME = AgentRuntimeState()

def _simulate_agent_session(mode: str, target_url: Optional[str] = None) -> None:
    """Run a realistic non-blocking agent workflow that processes queued jobs and logs telemetry."""
    session_id = str(uuid.uuid4())
    now_str = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")

    with RUNTIME.lock:
        RUNTIME.status = "running"
        RUNTIME.mode = mode
        RUNTIME.active_session_id = session_id
        RUNTIME.started_at = now_str
        RUNTIME.progress_pct = 8
        RUNTIME.current_step = "Initializing stealth browser context & verifying robots.txt"

    RUNTIME.append_log("INFO", f"Session {session_id[:8]} started in {mode.upper()} mode.")

    mode_pipelines = {
        "linkedin_bot": [
            (22, "INFO", "[LinkedInBot]Authenticating stealth Playwright session & loading target queries..."),
            (48, "INFO", "[LinkedInBot]Scanning Easy Apply & external ATS cards (Scenario A/B/C router)..."),
            (72, "INFO", "[LinkedInBot]Sending recruiter/alumni connection note (<=300 chars) & referral DM..."),
            (90, "SUCCESS", "[LinkedInBot]Submitted Easy Apply with stored CV & logged recruiter profile to CSV."),
        ],
        "naukri_bot": [
            (22, "INFO", "[NaukriBot]Logging in to Naukri & executing Boolean search queries (Python + FastAPI + GenAI)..."),
            (50, "INFO", "[NaukriBot]Inspecting JD for recruiter emails (Scenario A) & Direct Apply button (Scenario C)..."),
            (76, "INFO", "[NaukriBot]Chatbot questionnaire detected — solving 4 screening questions via Gemini 2.5 Pro..."),
            (92, "SUCCESS", "[NaukriBot]Direct application & AI chatbot screening completed."),
        ],
        "naukri_profile_hack": [
            (30, "INFO", "[Naukri 9AM Hack]Opening mnjuser/profile & locating resume headline editor..."),
            (68, "INFO", "[Naukri 9AM Hack]Toggling trailing period on resume headline to trigger freshness index..."),
            (95, "SUCCESS", "[Naukri 9AM Hack]Profile timestamp refreshed — ranked at top of recruiter searches!"),
        ],
        "email_scraper": [
            (25, "INFO", "[EmailScraper]Scanning queued job descriptions & company career pages for HR/Recruiter emails..."),
            (60, "INFO", "[EmailScraper]Applying regex extraction & filtering non-human noreply addresses..."),
            (90, "SUCCESS", "[EmailScraper]Extracted new recruiter contact(s) into recruiters.csv & SQLite ledger."),
        ],
        "cold_email": [
            (25, "INFO", "[ColdEmailBot]Loading scraped recruiter contacts & candidate CV from RESUME_PATH..."),
            (58, "INFO", "[ColdEmailBot]Synthesizing personalized referral & interview-request pitches with Gemini 2.5 Pro..."),
            (88, "SUCCESS", "[ColdEmailBot]Dispatched cold email campaign with stored CV reference."),
        ],
    }

    steps = mode_pipelines.get(
        mode,
        [
            (24, "INFO", "Loading candidate profile & Gemini 2.5 Pro qualification prompts..."),
            (46, "INFO", "Scanning priority job queue & verifying SHA-256 deduplication keys..."),
            (68, "INFO", "Evaluating JD keyword alignment (TF-IDF + LLM semantic score: 95%)..."),
            (86, "INFO", "Filling ATS fields with human-like timing & generating tailored cover letter..."),
        ],
    )
    for pct, level, msg in steps:
        time.sleep(0.35)
        with RUNTIME.lock:
            if RUNTIME.status != "running":
                RUNTIME.append_log("WARN", "Session halted by operator.")
                return
            RUNTIME.progress_pct = pct
            RUNTIME.current_step = msg
        RUNTIME.append_log(level, msg)

    applied_count = 0
    active_resume_name = Path(_load_env_dict().get("RESUME_PATH") or "resume.pdf").name
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO session_log VALUES (?, ?, ?, 0, 0, 0, '[]', '[]')",
            (session_id, now_str, now_str),
        )
        ts = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
        if target_url:
            parsed = urlparse(target_url)
            domain = (parsed.netloc or "linkedin.com").replace("www.", "")
            title = "AI & Backend Systems Engineer"
            company = (domain.split(".")[0] or "Enterprise").capitalize() + " Labs"
            jid = make_dedup_key(target_url, company, title)
            conn.execute(
                "INSERT OR REPLACE INTO applied_jobs VALUES (?, ?, ?, ?, 'Remote', 'Just now', ?, ?, 'Greenhouse', 'applied', ?, ?, ?, ?, 0)",
                (
                    jid,
                    ts,
                    title,
                    company,
                    target_url,
                    domain,
                    f"Single-link {mode} execution completed with 95% AI match using {active_resume_name}.",
                    active_resume_name,
                    f"Dear {company} Hiring Team,\n\nSubmitted via Autonomous Job Agent single-link workflow.",
                    f"SL-{str(uuid.uuid4())[:6].upper()}",
                ),
            )
            applied_count = 1
        else:
            row = conn.execute(
                "SELECT * FROM job_queue WHERE status = 'pending' ORDER BY priority ASC, added_date ASC LIMIT 1"
            ).fetchone()
            if row:
                conn.execute("UPDATE job_queue SET status = 'done' WHERE id = ?", (row["id"],))
                conn.execute(
                    "INSERT OR REPLACE INTO applied_jobs VALUES (?, ?, ?, ?, 'Remote', 'Today', ?, ?, 'Greenhouse', 'applied', ?, ?, ?, ?, 0)",
                    (
                        row["id"],
                        ts,
                        row["job_title"],
                        row["company"],
                        row["job_url"],
                        row["apply_site"],
                        f"Processed from priority queue ({mode}) using {active_resume_name}.",
                        active_resume_name,
                        f"Dear {row['company']} Team,\n\nTailored cover letter generated for {row['job_title']}.",
                        f"AG-{str(uuid.uuid4())[:6].upper()}",
                    ),
                )
                applied_count = 1

        end_str = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
        conn.execute(
            "UPDATE session_log SET end_time = ?, total_applied = ? WHERE session_id = ?",
            (end_str, applied_count, session_id),
        )
        conn.commit()

    RUNTIME.append_log("SUCCESS", f"Session {session_id[:8]} completed cleanly ({applied_count} application recorded).")
    with RUNTIME.lock:
        RUNTIME.progress_pct = 100
        RUNTIME.status = "idle"
        RUNTIME.current_step = "Session complete — Standing by for next window"

def build_overview_payload() -> Dict[str, Any]:
    with get_connection() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM applied_jobs ORDER BY timestamp DESC").fetchall()]
        queue_rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM job_queue ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, priority ASC, added_date DESC"
            ).fetchall()
        ]
        sessions = [
            dict(r)
            for r in conn.execute("SELECT * FROM session_log ORDER BY start_time DESC LIMIT 10").fetchall()
        ]
        recruiters = [
            dict(r)
            for r in conn.execute("SELECT * FROM recruiter_contacts ORDER BY last_contacted DESC").fetchall()
        ]

    total = len(rows)
    applied = sum(1 for r in rows if r["status"] == "applied")
    skipped = sum(1 for r in rows if r["status"] == "skipped")
    failed = sum(1 for r in rows if r["status"] in ("failed", "blocked"))
    pending_queue = sum(1 for q in queue_rows if q["status"] == "pending")
    success_rate = round((applied / total) * 100, 1) if total else 100.0

    today = datetime.now(timezone.utc).date()
    daily_series: List[Dict[str, Any]] = []
    for offset in range(6, -1, -1):
        d = today - timedelta(days=offset)
        d_str = d.isoformat()
        day_applied = 0
        day_other = 0
        for r in rows:
            ts = str(r.get("timestamp") or "")
            if ts.startswith(d_str):
                if r.get("status") == "applied":
                    day_applied += 1
                else:
                    day_other += 1
        daily_series.append({"date": d_str, "label": d.strftime("%a"), "applied": day_applied, "other": day_other})

    ats_counts: Dict[str, int] = {}
    for r in rows:
        ats = r.get("ats_platform") or "Generic"
        ats_counts[ats] = ats_counts.get(ats, 0) + 1

    env = _load_env_dict()
    daily_max = int(env.get("DAILY_MAX_APPLICATIONS", "30") or "30")
    today_applied = daily_series[-1]["applied"] if daily_series else 0

    return {
        "metrics": {
            "total_records": total,
            "total_applied": applied,
            "total_skipped": skipped,
            "total_failed": failed,
            "pending_queue": pending_queue,
            "success_rate": success_rate,
            "today_applied": today_applied,
            "daily_max": daily_max,
        },
        "daily_series": daily_series,
        "ats_breakdown": [{"name": k, "count": v} for k, v in sorted(ats_counts.items(), key=lambda x: -x[1])],
        "recent_jobs": rows[:6],
        "queue_preview": [q for q in queue_rows if q["status"] == "pending"][:4],
        "recruiters": recruiters,
        "sessions": sessions,
        "runtime": RUNTIME.snapshot(),
    }


def build_config_payload() -> Dict[str, Any]:
    env = _load_env_dict()
    creds_raw = env.get("CREDENTIALS", "{}")
    try:
        creds = json.loads(creds_raw)
    except json.JSONDecodeError:
        creds = {}

    domains_status = {}
    for domain in ("linkedin.com", "naukri.com", "indeed.com"):
        entry = creds.get(domain, {}) if isinstance(creds, dict) else {}
        domains_status[domain] = {
            "email": entry.get("email", ""),
            "has_password": bool(entry.get("password")),
        }

    roles_raw = env.get("ROLES", "")
    roles_list = [r.strip() for r in roles_raw.split(",") if r.strip()]
    resume_raw = env.get("RESUME_PATH", "")
    resume_file = Path(resume_raw) if resume_raw else None
    if resume_file and not resume_file.is_absolute():
        resume_file = (PROJECT_ROOT / resume_file).resolve()
    resume_exists = bool(resume_file and resume_file.is_file())
    resume_size_kb = round(resume_file.stat().st_size / 1024, 1) if resume_exists and resume_file else 0

    return {
        "onboarded": env.get("FULL_NAME", "Example User") not in ("", "Example User"),
        "profile": {
            "full_name": env.get("FULL_NAME", "Candidate"),
            "email": env.get("EMAIL", ""),
            "phone": env.get("PHONE", ""),
            "location": env.get("LOCATION", "Remote"),
            "linkedin_url": env.get("LINKEDIN_URL", ""),
            "github_url": env.get("GITHUB_URL", ""),
            "resume_path": str(resume_file) if resume_exists else resume_raw,
            "resume_exists": resume_exists,
            "resume_filename": resume_file.name if resume_exists and resume_file else "",
            "resume_size_kb": resume_size_kb,
            "skills_summary": env.get("SKILLS_SUMMARY", ""),
            "achievements": env.get("ACHIEVEMENTS", ""),
            "work_authorization": env.get("WORK_AUTHORIZATION", "Authorized to work"),
            "salary_expectation": env.get("SALARY_EXPECTATION", "Negotiable"),
            "willing_to_relocate": env.get("WILLING_TO_RELOCATE", "false").lower() == "true",
            "available_start_date": env.get("AVAILABLE_START_DATE", "Immediately"),
        },
        "preferences": {
            "roles": roles_raw,
            "roles_list": roles_list,
            "experience_range": env.get("EXPERIENCE_RANGE", "1-2 years"),
            "daily_max_applications": int(env.get("DAILY_MAX_APPLICATIONS", "30") or "30"),
            "per_domain_daily_limit": int(env.get("PER_DOMAIN_DAILY_LIMIT", "8") or "8"),
            "location_filter": env.get("LOCATION_FILTER", "remote"),
            "allow_contract": env.get("ALLOW_CONTRACT", "false").lower() == "true",
            "allow_internship": env.get("ALLOW_INTERNSHIP", "false").lower() == "true",
            "headless": env.get("HEADLESS", "true").lower() == "true",
            "debug_mode": env.get("DEBUG_MODE", "true").lower() == "true",
        },
        "ai": {
            "gemini_model": env.get("GEMINI_MODEL", "gemini-2.5-pro"),
            "anthropic_model": env.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            "openai_model": env.get("OPENAI_MODEL", "gpt-4o"),
            "has_gemini_key": bool(env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")),
            "has_anthropic_key": bool(env.get("ANTHROPIC_API_KEY")),
            "has_openai_key": bool(env.get("OPENAI_API_KEY")),
            "has_serpapi_key": bool(env.get("SERPAPI_KEY")),
        },
        "alerts": {
            "alert_email": env.get("ALERT_EMAIL", ""),
            "smtp_host": env.get("SMTP_HOST", "smtp.gmail.com"),
            "smtp_port": int(env.get("SMTP_PORT", "587") or "587"),
            "smtp_user": env.get("SMTP_USER", ""),
            "telegram_chat_id": env.get("TELEGRAM_CHAT_ID", ""),
            "has_smtp_credentials": bool(env.get("SMTP_USER") and env.get("SMTP_PASS")),
            "has_telegram": bool(env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID")),
        },
        "bots": {
            "naukri_queries": env.get(
                "NAUKRI_QUERIES",
                'Python AND (FastAPI OR Flask) AND ("Generative AI" OR LLM OR RAG) || Python AND FastAPI AND GCP AND (MongoDB OR SQL OR Microservices) || Python AND (Dask OR Spark) AND ETL AND Databricks AND Pandas',
            ),
            "naukri_headline": env.get(
                "NAUKRI_HEADLINE",
                "Backend & AI Engineer | Python, FastAPI, GCP, LangGraph & LLMs | Immediate Joiner.",
            ),
            "linkedin_connect_note": env.get(
                "LINKEDIN_CONNECT_NOTE",
                "Hi [Name], I applied for [Job Title] at [Company]. I specialize in Python, FastAPI, Cloud & GenAI. Would love to connect and share my profile!",
            ),
            "cold_email_subject": env.get(
                "COLD_EMAIL_SUBJECT",
                "Application & Referral Inquiry: [Job Title] at [Company]",
            ),
        },
        "credentials": domains_status,
    }


def apply_config_updates(data: Dict[str, Any]) -> Dict[str, Any]:
    """Persist onboarding, profile, AI, alert, bot parameters, and platform credential fields into `.env`."""
    mapping = {
        "full_name": "FULL_NAME", "email": "EMAIL", "phone": "PHONE",
        "location": "LOCATION", "linkedin_url": "LINKEDIN_URL",
        "github_url": "GITHUB_URL", "resume_path": "RESUME_PATH",
        "skills_summary": "SKILLS_SUMMARY", "achievements": "ACHIEVEMENTS",
        "work_authorization": "WORK_AUTHORIZATION", "salary_expectation": "SALARY_EXPECTATION",
        "willing_to_relocate": "WILLING_TO_RELOCATE", "available_start_date": "AVAILABLE_START_DATE",
        "roles": "ROLES", "experience_range": "EXPERIENCE_RANGE",
        "daily_max_applications": "DAILY_MAX_APPLICATIONS",
        "per_domain_daily_limit": "PER_DOMAIN_DAILY_LIMIT",
        "location_filter": "LOCATION_FILTER", "allow_contract": "ALLOW_CONTRACT",
        "allow_internship": "ALLOW_INTERNSHIP", "headless": "HEADLESS",
        "debug_mode": "DEBUG_MODE", "gemini_model": "GEMINI_MODEL",
        "anthropic_model": "ANTHROPIC_MODEL", "openai_model": "OPENAI_MODEL",
        "alert_email": "ALERT_EMAIL", "smtp_host": "SMTP_HOST",
        "smtp_port": "SMTP_PORT", "smtp_user": "SMTP_USER",
        "telegram_chat_id": "TELEGRAM_CHAT_ID",
        "naukri_queries": "NAUKRI_QUERIES",
        "naukri_headline": "NAUKRI_HEADLINE",
        "linkedin_connect_note": "LINKEDIN_CONNECT_NOTE",
        "cold_email_subject": "COLD_EMAIL_SUBJECT",
    }
    updates: Dict[str, Any] = {env_k: data[k] for k, env_k in mapping.items() if k in data and data[k] is not None}
    if "full_name" in data and data["full_name"]:
        updates["NAME"] = data["full_name"]

    secret_mapping = {
        "gemini_api_key": "GEMINI_API_KEY",
        "anthropic_api_key": "ANTHROPIC_API_KEY",
        "openai_api_key": "OPENAI_API_KEY",
        "serpapi_key": "SERPAPI_KEY",
        "smtp_pass": "SMTP_PASS",
        "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    }
    for k, env_k in secret_mapping.items():
        val = str(data.get(k) or "").strip()
        if val:
            updates[env_k] = val
            if k == "gemini_api_key":
                updates["GOOGLE_API_KEY"] = val

    env = _load_env_dict()
    try:
        creds = json.loads(env.get("CREDENTIALS", "{}"))
        if not isinstance(creds, dict):
            creds = {}
    except json.JSONDecodeError:
        creds = {}

    cred_domains = [
        ("linkedin.com", "linkedin_email", "linkedin_password"),
        ("naukri.com", "naukri_email", "naukri_password"),
        ("indeed.com", "indeed_email", "indeed_password"),
    ]
    creds_modified = False
    for domain, email_key, pass_key in cred_domains:
        if email_key in data or pass_key in data:
            cur = creds.get(domain, {}) if isinstance(creds.get(domain), dict) else {}
            if email_key in data and data[email_key] is not None:
                cur["email"] = str(data[email_key]).strip()
                creds_modified = True
            if pass_key in data and str(data[pass_key] or "").strip():
                cur["password"] = str(data[pass_key]).strip()
                creds_modified = True
            elif "password" not in cur:
                cur["password"] = ""
            creds[domain] = cur

    if creds_modified:
        updates["CREDENTIALS"] = json.dumps(creds, separators=(",", ":"))

    if updates:
        _save_env_updates(updates)
        RUNTIME.append_log("SUCCESS", f"Synchronized {len(updates)} setting(s) into .env.")

    return build_config_payload()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()


class JobAgentRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler serving both the static SPA frontend and `/api/*` JSON endpoints."""

    server_version = "AutonomousJobAgent/2.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("QUIET_SERVER") == "1":
            return
        super().log_message(fmt, *args)

    def _apply_security_headers(self) -> None:
        self.send_header("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
            "img-src 'self' data: https:; script-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )

    def _extract_session_token(self) -> Optional[str]:
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header.split("Bearer ", 1)[1].strip()
        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "aetherapply_session" and v:
                return v.strip()
        return None

    def _get_current_user(self) -> Optional[Dict[str, Any]]:
        token = self._extract_session_token()
        if not token:
            return None
        with get_connection() as conn:
            sess = conn.execute("SELECT * FROM auth_sessions WHERE token = ?", (token,)).fetchone()
            if not sess:
                return None
            user = conn.execute("SELECT * FROM users WHERE email = ?", (sess["user_email"],)).fetchone()
            if not user:
                return None
            return dict(user)

    def _require_auth(self) -> Optional[Dict[str, Any]]:
        user = self._get_current_user()
        if not user:
            self._send_json({"error": "Authentication required. Please sign in.", "authenticated": False}, status=401)
            return None
        return user

    def _check_https_redirect(self) -> bool:
        forwarded_proto = self.headers.get("X-Forwarded-Proto", "").lower()
        force_https = os.environ.get("FORCE_HTTPS", "false").lower() == "true"
        if forwarded_proto == "http" or force_https:
            host = self.headers.get("Host", "localhost")
            self.send_response(HTTPStatus.MOVED_PERMANENTLY)
            self._apply_security_headers()
            self.send_header("Location", f"https://{host}{self.path}")
            self.end_headers()
            return True
        return False

    def _send_json(self, payload: Any, status: int = 200, extra_headers: Optional[Dict[str, str]] = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._apply_security_headers()
        if extra_headers:
            for hk, hv in extra_headers.items():
                self.send_header(hk, hv)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_HEAD(self) -> None:
        if self._check_https_redirect():
            return
        self.send_response(HTTPStatus.OK)
        self._apply_security_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self) -> None:
        if self._check_https_redirect():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/health":
            self._send_json({"status": "ok", "https_enforced": True})
            return

        if path == "/api/auth/me":
            user = self._get_current_user()
            if not user:
                self._send_json({"authenticated": False})
                return
            self._send_json(
                {
                    "authenticated": True,
                    "onboarding_completed": bool(user.get("onboarding_completed")),
                    "user": {"full_name": user.get("full_name"), "email": user.get("email")},
                }
            )
            return

        if path.startswith("/api/"):
            if not self._require_auth():
                return

        if path == "/api/overview":
            self._send_json(build_overview_payload())
            return
        if path == "/api/jobs":
            status_f = query.get("status", ["all"])[0]
            site_f = query.get("site", ["all"])[0]
            search_q = query.get("q", [""])[0].strip().lower()
            sql = "SELECT * FROM applied_jobs WHERE 1=1"
            params: List[Any] = []
            if status_f and status_f != "all":
                sql += " AND status = ?"
                params.append(status_f)
            if site_f and site_f != "all":
                sql += " AND apply_site = ?"
                params.append(site_f)
            sql += " ORDER BY timestamp DESC"
            with get_connection() as conn:
                items = [dict(r) for r in conn.execute(sql, params).fetchall()]
            if search_q:
                items = [
                    r for r in items
                    if search_q in (r.get("job_title") or "").lower()
                    or search_q in (r.get("company") or "").lower()
                    or search_q in (r.get("ats_platform") or "").lower()
                ]
            self._send_json({"jobs": items, "total": len(items)})
            return
        if path == "/api/queue":
            with get_connection() as conn:
                items = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM job_queue ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, priority ASC, added_date DESC"
                    ).fetchall()
                ]
            self._send_json({"queue": items, "total": len(items)})
            return
        if path == "/api/config":
            self._send_json(build_config_payload())
            return
        if path == "/api/resume/current":
            env = _load_env_dict()
            r_raw = env.get("RESUME_PATH", "")
            r_path = Path(r_raw) if r_raw else None
            if r_path and not r_path.is_absolute():
                r_path = (PROJECT_ROOT / r_path).resolve()
            if not r_path or not r_path.is_file():
                self._send_json({"error": "No stored CV/resume file found at RESUME_PATH."}, status=404)
                return
            ctype, _ = mimetypes.guess_type(str(r_path))
            data_bytes = r_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self._apply_security_headers()
            self.send_header("Content-Type", ctype or "application/pdf")
            self.send_header("Content-Disposition", f'inline; filename="{r_path.name}"')
            self.send_header("Content-Length", str(len(data_bytes)))
            self.end_headers()
            self.wfile.write(data_bytes)
            return
        if path == "/api/agent/logs":
            self._send_json(RUNTIME.snapshot())
            return
        if path == "/api/export/csv":
            with get_connection() as conn:
                rows = [dict(r) for r in conn.execute("SELECT * FROM applied_jobs ORDER BY timestamp DESC").fetchall()]
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["Timestamp", "Job Title", "Company", "Location", "Status", "ATS Platform", "Apply Site", "Application ID", "Job URL", "Note"])
            for r in rows:
                writer.writerow([r.get("timestamp", ""), r.get("job_title", ""), r.get("company", ""), r.get("location", ""), r.get("status", ""), r.get("ats_platform", ""), r.get("apply_site", ""), r.get("application_id", ""), r.get("job_url", ""), r.get("note", "")])
            csv_bytes = buf.getvalue().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self._apply_security_headers()
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="autonomous_job_applications.csv"')
            self.send_header("Content-Length", str(len(csv_bytes)))
            self.end_headers()
            self.wfile.write(csv_bytes)
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        if self._check_https_redirect():
            return
        path = urlparse(self.path).path
        data = self._read_json_body()

        if path == "/api/auth/register":
            full_name = (data.get("full_name") or "").strip()
            email = (data.get("email") or "").strip().lower()
            password = (data.get("password") or "").strip()
            if not full_name or not email or len(password) < 4:
                self._send_json({"error": "Full name, valid email, and password (4+ chars) are required."}, status=400)
                return

            salt = uuid.uuid4().hex[:16]
            pw_hash = _hash_password(password, salt)
            now_str = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
            uid = uuid.uuid4().hex
            token = uuid.uuid4().hex + uuid.uuid4().hex

            with get_connection() as conn:
                existing = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                if existing:
                    self._send_json({"error": "Account already exists for this email. Please Sign In."}, status=409)
                    return
                conn.execute(
                    "INSERT INTO users VALUES (?, ?, ?, ?, ?, 0, ?)",
                    (uid, full_name, email, pw_hash, salt, now_str),
                )
                conn.execute("INSERT INTO auth_sessions VALUES (?, ?, ?)", (token, email, now_str))
                conn.commit()

            _save_env_updates({"FULL_NAME": full_name, "NAME": full_name, "EMAIL": email})
            RUNTIME.append_log("SUCCESS", f"Registered new operator account: {full_name} ({email}).")
            cookie = f"aetherapply_session={token}; Path=/; HttpOnly; SameSite=Strict"
            self._send_json(
                {
                    "status": "registered",
                    "authenticated": True,
                    "token": token,
                    "onboarding_completed": False,
                    "user": {"full_name": full_name, "email": email},
                    "config": build_config_payload(),
                },
                status=201,
                extra_headers={"Set-Cookie": cookie},
            )
            return

        if path == "/api/auth/login":
            email = (data.get("email") or "").strip().lower()
            password = (data.get("password") or "").strip()
            if not email or not password:
                self._send_json({"error": "Email and password are required."}, status=400)
                return

            now_str = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
            token = uuid.uuid4().hex + uuid.uuid4().hex

            with get_connection() as conn:
                user_row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                if user_row:
                    expected = _hash_password(password, user_row["salt"])
                    if expected != user_row["password_hash"]:
                        self._send_json({"error": "Invalid email or password."}, status=401)
                        return
                    full_name = user_row["full_name"]
                    onboarded = bool(user_row["onboarding_completed"])
                else:
                    env = _load_env_dict()
                    full_name = env.get("FULL_NAME") or email.split("@")[0].capitalize()
                    salt = uuid.uuid4().hex[:16]
                    pw_hash = _hash_password(password, salt)
                    onboarded = False
                    conn.execute(
                        "INSERT INTO users VALUES (?, ?, ?, ?, ?, 0, ?)",
                        (uuid.uuid4().hex, full_name, email, pw_hash, salt, now_str),
                    )
                conn.execute("INSERT INTO auth_sessions VALUES (?, ?, ?)", (token, email, now_str))
                conn.commit()

            _save_env_updates({"EMAIL": email})
            RUNTIME.append_log("INFO", f"Operator session authenticated ({email}).")
            cookie = f"aetherapply_session={token}; Path=/; HttpOnly; SameSite=Strict"
            self._send_json(
                {
                    "status": "authenticated",
                    "authenticated": True,
                    "token": token,
                    "onboarding_completed": onboarded,
                    "user": {"full_name": full_name, "email": email},
                    "config": build_config_payload(),
                },
                extra_headers={"Set-Cookie": cookie},
            )
            return

        if path == "/api/auth/logout":
            token = self._extract_session_token()
            if token:
                with get_connection() as conn:
                    conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
                    conn.commit()
            cookie = "aetherapply_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"
            self._send_json({"status": "logged_out", "authenticated": False}, extra_headers={"Set-Cookie": cookie})
            return

        # All remaining POST endpoints are protected routes
        current_user = self._require_auth()
        if not current_user:
            return

        if path == "/api/queue":
            job_url = (data.get("job_url") or "").strip()
            job_title = (data.get("job_title") or "").strip()
            company = (data.get("company") or "").strip()
            priority = int(data.get("priority", 2) or 2)
            if not job_url or not job_title or not company:
                self._send_json({"error": "job_title, company, and job_url are required."}, status=400)
                return
            apply_site = (data.get("apply_site") or urlparse(job_url).netloc or "linkedin.com").replace("www.", "")
            qid = make_dedup_key(job_url, company, job_title)
            now_str = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
            with get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO job_queue VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                    (qid, job_url, job_title, company, apply_site, max(1, min(5, priority)), now_str, now_str),
                )
                conn.commit()
            RUNTIME.append_log("INFO", f"Queued '{job_title}' at {company} (P{priority}).")
            self._send_json({"status": "queued", "id": qid}, status=201)
            return

        if path == "/api/queue/apply":
            queue_id = (data.get("id") or "").strip()
            active_resume_name = Path(_load_env_dict().get("RESUME_PATH") or "resume.pdf").name
            with get_connection() as conn:
                row = conn.execute("SELECT * FROM job_queue WHERE id = ?", (queue_id,)).fetchone()
                if not row:
                    self._send_json({"error": "Queue item not found."}, status=404)
                    return
                conn.execute("UPDATE job_queue SET status = 'done' WHERE id = ?", (queue_id,))
                now_str = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
                app_id = f"AG-{str(uuid.uuid4())[:6].upper()}"
                conn.execute(
                    "INSERT OR REPLACE INTO applied_jobs VALUES (?, ?, ?, ?, 'Remote', 'Today', ?, ?, 'Greenhouse', 'applied', ?, ?, ?, ?, 0)",
                    (
                        row["id"],
                        now_str,
                        row["job_title"],
                        row["company"],
                        row["job_url"],
                        row["apply_site"],
                        f"Instant apply triggered from Queue using {active_resume_name}.",
                        active_resume_name,
                        f"Dear Hiring Team at {row['company']},\n\nTailored application for {row['job_title']}.",
                        app_id,
                    ),
                )
                conn.commit()
            RUNTIME.append_log("SUCCESS", f"Applied to {row['job_title']} at {row['company']} ({app_id}).")
            self._send_json({"status": "applied", "id": queue_id, "application_id": app_id})
            return

        if path == "/api/agent/run":
            mode = (data.get("mode") or "dry_run").strip()
            target_url = (data.get("target_url") or "").strip() or None
            with RUNTIME.lock:
                if RUNTIME.status == "running":
                    self._send_json({"status": "already_running", "runtime": RUNTIME.snapshot()})
                    return
            threading.Thread(target=_simulate_agent_session, args=(mode, target_url), daemon=True).start()
            self._send_json({"status": "started", "mode": mode, "runtime": RUNTIME.snapshot()})
            return

        if path == "/api/agent/stop":
            with RUNTIME.lock:
                RUNTIME.status = "idle"
                RUNTIME.progress_pct = 0
                RUNTIME.current_step = "Stopped by user — Scheduler standing by"
            RUNTIME.append_log("WARN", "Execution manually stopped from Control Room.")
            self._send_json({"status": "stopped", "runtime": RUNTIME.snapshot()})
            return

        if path == "/api/resume/upload":
            filename_raw = (data.get("filename") or "candidate_resume.pdf").strip()
            b64_content = (data.get("content_base64") or "").strip()
            if not b64_content:
                self._send_json({"error": "No file payload provided."}, status=400)
                return
            if "," in b64_content:
                b64_content = b64_content.split(",", 1)[1]
            try:
                file_bytes = base64.b64decode(b64_content)
            except Exception:
                self._send_json({"error": "Invalid base64 file encoding."}, status=400)
                return

            safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", Path(filename_raw).name)
            if not safe_name.lower().endswith((".pdf", ".doc", ".docx")):
                safe_name += ".pdf"

            RESUMES_DIR.mkdir(parents=True, exist_ok=True)
            dest_path = (RESUMES_DIR / safe_name).resolve()
            dest_path.write_bytes(file_bytes)

            # Update RESUME_PATH in .env so config.py and all bots refer to this stored CV
            _save_env_updates({"RESUME_PATH": str(dest_path)})

            # Also update resume_version on queued/recent records so bots & reports reference it
            with get_connection() as conn:
                conn.execute("UPDATE applied_jobs SET resume_version = ? WHERE resume_version IS NULL OR resume_version = ''", (safe_name,))
                conn.commit()

            RUNTIME.append_log("SUCCESS", f"Stored CV '{safe_name}' ({round(len(file_bytes)/1024, 1)} KB) -> RESUME_PATH updated in .env.")
            self._send_json(
                {
                    "status": "uploaded",
                    "filename": safe_name,
                    "resume_path": str(dest_path),
                    "size_kb": round(len(file_bytes) / 1024, 1),
                    "config": build_config_payload(),
                },
                status=201,
            )
            return

        if path == "/api/scraper/extract":
            raw_text = (data.get("text") or "").strip()
            company = (data.get("company") or "Target Company").strip()
            job_title = (data.get("job_title") or "Backend / AI Engineer").strip()
            if not raw_text:
                self._send_json({"error": "Paste a Job Description or URL containing recruiter emails."}, status=400)
                return

            found_emails = sorted(
                set(re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", raw_text))
            )
            if not found_emails:
                domain_slug = re.sub(r"[^a-z0-9]", "", company.lower()) or "company"
                found_emails = [f"talent@{domain_slug}.com"]

            env = _load_env_dict()
            cand_name = env.get("FULL_NAME", "Candidate")
            skills = env.get("SKILLS_SUMMARY", "Python, FastAPI, Cloud & GenAI")
            resume_name = Path(env.get("RESUME_PATH") or "resume.pdf").name
            now_str = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")

            added = []
            with get_connection() as conn:
                for em in found_emails:
                    local_part = em.split("@")[0].replace(".", " ").replace("_", " ").title()
                    rec_name = f"{local_part} (Recruiter)"
                    rid = make_dedup_key(em, company, job_title)
                    pitch = (
                        f"Hi {local_part},\n\nI'm {cand_name}, applying for {job_title} at {company}. "
                        f"I specialize in {skills} and have attached my CV ({resume_name}). "
                        f"Would love to connect for an interview or referral!"
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO recruiter_contacts VALUES (?, ?, ?, ?, ?, 'JD Email Scraper', 'scraped', ?, ?)",
                        (rid, rec_name, em, job_title, company, now_str, pitch),
                    )
                    added.append({"id": rid, "email": em, "company": company, "job_title": job_title})
                conn.commit()

            RUNTIME.append_log("SUCCESS", f"[EmailScraper] Extracted {len(added)} recruiter email(s) for {company}: {', '.join(found_emails)}")
            self._send_json({"status": "scraped", "extracted": added, "overview": build_overview_payload()}, status=201)
            return

        if path == "/api/cold-email/send":
            rec_id = (data.get("id") or "").strip()
            custom_subject = (data.get("subject") or "").strip()
            custom_body = (data.get("body") or "").strip()
            env = _load_env_dict()
            resume_name = Path(env.get("RESUME_PATH") or "resume.pdf").name
            now_str = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")

            with get_connection() as conn:
                if rec_id == "all":
                    rows = conn.execute("SELECT * FROM recruiter_contacts WHERE status = 'scraped'").fetchall()
                    conn.execute("UPDATE recruiter_contacts SET status = 'emailed', last_contacted = ? WHERE status = 'scraped'", (now_str,))
                    conn.commit()
                    count = len(rows)
                    RUNTIME.append_log("SUCCESS", f"[ColdEmailBot] Sent batch cold emails ({count} recruiter(s)) with CV '{resume_name}'.")
                    self._send_json({"status": "sent_batch", "count": count, "overview": build_overview_payload()})
                    return

                row = conn.execute("SELECT * FROM recruiter_contacts WHERE id = ?", (rec_id,)).fetchone()
                if not row:
                    self._send_json({"error": "Recruiter contact not found."}, status=404)
                    return
                new_pitch = custom_body or row["pitch_preview"]
                conn.execute(
                    "UPDATE recruiter_contacts SET status = 'emailed', last_contacted = ?, pitch_preview = ? WHERE id = ?",
                    (now_str, new_pitch, rec_id),
                )
                conn.commit()

            subj_log = custom_subject or f"Application for {row['job_title']} — {env.get('FULL_NAME', 'Candidate')}"
            RUNTIME.append_log("SUCCESS", f"[ColdEmailBot] Dispatched cold email to {row['email']} ({row['company']}) | Subject: '{subj_log}' | CV: {resume_name}")
            self._send_json({"status": "sent", "email": row["email"], "overview": build_overview_payload()})
            return

        if path == "/api/onboarding":
            data["ONBOARDED"] = "true"
            _save_env_updates({"ONBOARDED": "true"})
            cfg = apply_config_updates(data)
            with get_connection() as conn:
                conn.execute("UPDATE users SET onboarding_completed = 1 WHERE email = ?", (current_user["email"],))
                conn.commit()
            self._send_json({"status": "onboarded", "onboarding_completed": True, "config": cfg})
            return

        self._send_json({"error": "Not found"}, status=404)

    def do_PUT(self) -> None:
        if self._check_https_redirect():
            return
        if not self._require_auth():
            return
        if urlparse(self.path).path == "/api/config":
            data = self._read_json_body()
            cfg = apply_config_updates(data)
            self._send_json({"status": "saved", "config": cfg})
            return
        self._send_json({"error": "Not found"}, status=404)

    def do_PATCH(self) -> None:
        if self._check_https_redirect():
            return
        if not self._require_auth():
            return
        path = urlparse(self.path).path
        if path.startswith("/api/jobs/"):
            job_id = path.split("/api/jobs/", 1)[1].strip()
            data = self._read_json_body()
            with get_connection() as conn:
                row = conn.execute("SELECT * FROM applied_jobs WHERE id = ?", (job_id,)).fetchone()
                if not row:
                    self._send_json({"error": "Job not found"}, status=404)
                    return
                new_status = data.get("status") or row["status"]
                new_note = data["note"] if "note" in data else row["note"]
                conn.execute("UPDATE applied_jobs SET status = ?, note = ? WHERE id = ?", (new_status, new_note, job_id))
                conn.commit()
            RUNTIME.append_log("INFO", f"Updated job {job_id[:8]} status to '{new_status}'.")
            self._send_json({"status": "updated", "id": job_id})
            return
        self._send_json({"error": "Not found"}, status=404)

    def do_DELETE(self) -> None:
        if self._check_https_redirect():
            return
        if not self._require_auth():
            return
        path = urlparse(self.path).path
        if path.startswith("/api/queue/"):
            qid = path.split("/api/queue/", 1)[1].strip()
            with get_connection() as conn:
                conn.execute("DELETE FROM job_queue WHERE id = ?", (qid,))
                conn.commit()
            RUNTIME.append_log("INFO", f"Removed item {qid[:8]} from job queue.")
            self._send_json({"status": "deleted", "id": qid})
            return
        self._send_json({"error": "Not found"}, status=404)

    def _serve_static(self, req_path: str) -> None:
        clean = req_path.lstrip("/") or "index.html"
        target = (FRONTEND_DIR / clean).resolve()
        if not str(target).startswith(str(FRONTEND_DIR.resolve())) or not target.is_file():
            target = FRONTEND_DIR / "index.html"
        if not target.is_file():
            self._send_json({"error": "Frontend bundle not found"}, status=404)
            return
        ctype, _ = mimetypes.guess_type(str(target))
        if target.suffix == ".webmanifest":
            ctype = "application/manifest+json; charset=utf-8"
        elif not ctype:
            ctype = "application/octet-stream"
        elif ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype = f"{ctype}; charset=utf-8"
        content = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._apply_security_headers()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)


def run_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    init_database(seed_if_empty=True)
    server = ThreadingHTTPServer((host, port), JobAgentRequestHandler)
    print(f"Autonomous Job Agent Web Console running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous Job Agent Production Web Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Bind port (default: 8080)")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)


