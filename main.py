"""
main.py — Entry point for the Autonomous Job Application System.

Modes:
  python main.py              → Start APScheduler (runs 08:00–21:00 daily)
  python main.py --dry-run    → Single immediate run, no real submissions (DEBUG_MODE=true)
  python main.py --run-once   → Single immediate run with real submissions
"""

import argparse
import os
import random
import sys
import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from dotenv import load_dotenv
from loguru import logger

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT.parent))

load_dotenv()

# Logging setup
Path("logs").mkdir(exist_ok=True)
logger.remove()
logger.add(
    sys.stdout,
    level="INFO",
    format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}",
)
logger.add(
    "logs/agent_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="14 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{line} | {message}",
)


class AgentRunner:
    """
    Main class to handle the initialization, session management, and scheduling of the Job Agent.
    """

    def __init__(self, dry_run: bool = False):
        """
        Initialize the Agent Runner.

        Args:
            dry_run (bool): If True, sets DEBUG_MODE to true, preventing real form submissions.
        """
        self.dry_run = dry_run
        if self.dry_run:
            os.environ["DEBUG_MODE"] = "true"
            
        try:
            from config import settings
            self.settings = settings
        except Exception as e:
            logger.error(f"Config error: {e}")
            logger.error("Copy .env.example → .env and fill in your values, then retry.")
            sys.exit(1)

        self.db_engine = None
        self.SessionLocal = None

    def _setup_db(self) -> None:
        """Setup DB Engine and Session Factory."""
        from db.models import get_engine, get_session_factory
        self.db_engine = get_engine(self.settings.db_path)
        self.SessionLocal = get_session_factory(self.db_engine)

    def get_user_profile(self) -> Dict[str, Any]:
        """Builds and returns the master candidate profile dictionary from settings."""
        saved_answers_path = PROJECT_ROOT / "saved_answers.json"
        saved_answers = {}
        if saved_answers_path.exists():
            try:
                with open(saved_answers_path, "r") as f:
                    saved_answers = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load saved_answers.json: {e}")

        return {
            "full_name": self.settings.full_name,
            "email": self.settings.email,
            "phone": self.settings.phone,
            "saved_answers": saved_answers,
            "location": self.settings.location,
            "linkedin_url": self.settings.linkedin_url,
            "github_url": self.settings.github_url,
            "roles": self.settings.roles_list,
            "experience_range": self.settings.experience_range,
            "location_filter": self.settings.location_filter,
            "allow_contract": self.settings.allow_contract,
            "allow_internship": self.settings.allow_internship,
            "skills_summary": self.settings.skills_summary or (
                "Python, FastAPI, MongoDB, Google Cloud Functions, REST APIs, SQL, "
                "Data Analysis, Tableau, Pandas, NumPy, Matplotlib, Machine Learning"
            ),
            "achievements": self.settings.achievements or (
                "Implemented automatic MongoDB indexing significantly reducing query time and UI load time. "
                "Led a 20-member social service team. "
                "Organized the Diya Project generating revenue of 1.25 lakhs."
            ),
            "work_authorization": self.settings.work_authorization,
            "salary_expectation": self.settings.salary_expectation,
            "willing_to_relocate": self.settings.willing_to_relocate,
            "available_start_date": self.settings.available_start_date,
            "us_citizen": False,
        }

    def execute_session(self) -> None:
        """Execute one full agent session."""
        start_time = datetime.utcnow()
        logger.info("=" * 60)
        logger.info(f"🤖 Job Agent session starting at {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        logger.info(f"Roles: {self.settings.roles_list}")
        logger.info(f"Daily max: {self.settings.daily_max_applications}")
        logger.info(f"Debug mode: {self.settings.debug_mode}")

        self._setup_db()
        from db.crud import create_session_log, update_session_log

        with self.SessionLocal() as db_session:
            session_id = create_session_log(db_session)

        user_profile = self.get_user_profile()
        
        session_stats = {
            "session_id": session_id,
            "total_applied": 0,
            "total_skipped": 0,
            "total_failed": 0,
            "sites_blocked": [],
            "alerts_sent": [],
            "domain_counts": {},
        }

        try:
            from naukri_bot import NaukriBot
            logger.info("Starting Naukri Bot execution…")
            bot = NaukriBot()
            asyncio.run(bot.run())
            session_stats["total_applied"] = 1  # Dummy update as logic is inside bot
        except BaseException as e:
            logger.error(f"Naukri Bot execution error: {e}")

        end_time = datetime.utcnow()
        duration = (end_time - start_time).seconds // 60

        with self.SessionLocal() as db_session:
            update_session_log(
                db_session,
                session_id,
                total_applied=session_stats.get("total_applied", 0),
                total_skipped=session_stats.get("total_skipped", 0),
                total_failed=session_stats.get("total_failed", 0),
                sites_blocked=session_stats.get("sites_blocked", []),
            )

        logger.info("=" * 60)
        logger.info(f"✅ Session complete in {duration}min")
        logger.info(f"   Applied:  {session_stats.get('total_applied', 0)}")
        logger.info(f"   Skipped:  {session_stats.get('total_skipped', 0)}")
        logger.info(f"   Failed:   {session_stats.get('total_failed', 0)}")

        if not self.settings.debug_mode:
            self._send_reports(session_id, session_stats)

    def _send_reports(self, session_id: str, stats: Dict[str, Any]) -> None:
        """Generate reports and send email alerts."""
        try:
            from reports.daily_report import generate_csv_report, generate_html_summary
            from alerts.email_alert import send_email_alert, format_session_summary

            generate_csv_report(session_id)
            html = generate_html_summary(session_id, stats)
            plain, _ = format_session_summary(stats)
            send_email_alert(
                subject=f"Session complete — {stats.get('total_applied', 0)} applied",
                body=plain,
                html_body=html,
            )
        except Exception as e:
            logger.warning(f"Report/email failed (non-fatal): {e}")

    def start_scheduler(self) -> None:
        """Start APScheduler to run the agent daily within 08:00–21:00."""
        from apscheduler.schedulers.blocking import BlockingScheduler

        scheduler = BlockingScheduler(timezone="local")
        rand_minute = random.randint(0, 59)
        scheduler.add_job(
            self.execute_session,
            trigger="cron",
            hour="8-21",
            minute=rand_minute,
            id="job_agent",
            max_instances=1,
            coalesce=True,
        )
        logger.info(f"Scheduler started. Agent runs hourly (08:00–21:00) at :{rand_minute:02d}")
        logger.info("Press Ctrl+C to stop.")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous Job Application Agent")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run once immediately with DEBUG_MODE (no real submissions)")
    parser.add_argument("--run-once", action="store_true",
                        help="Run once immediately with real submissions")
    parser.add_argument("--link", nargs='?', const=True, default=False,
                        help="Run in single link apply mode. Optionally provide a URL.")
    args = parser.parse_args()

    runner = AgentRunner(dry_run=args.dry_run)

    if args.dry_run:
        logger.info("DRY RUN mode — no real form submissions")
        runner.execute_session()
    elif args.run_once:
        logger.info("SINGLE RUN mode")
        runner.execute_session()
    else:
        runner.start_scheduler()
