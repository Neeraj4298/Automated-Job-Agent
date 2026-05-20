"""
reports/daily_report.py — Generate CSV and HTML summary reports.
"""

import csv
import io
from datetime import datetime
from pathlib import Path
from typing import List

from loguru import logger


def _get_session_jobs(session_id: str, db_session) -> List:
    """Fetch all jobs logged during a session."""
    from db.models import AppliedJob, SessionLog
    log = db_session.query(SessionLog).filter_by(session_id=session_id).first()
    if not log or not log.start_time:
        return []
    return (
        db_session.query(AppliedJob)
        .filter(AppliedJob.timestamp >= log.start_time)
        .order_by(AppliedJob.timestamp)
        .all()
    )


def generate_csv_report(session_id: str) -> str:
    """
    Export all applications from a session to a CSV file.
    Returns the path to the CSV file.
    """
    from config import settings
    from db.models import get_engine, get_session_factory

    engine = get_engine(settings.db_path)
    Session = get_session_factory(engine)

    reports_dir = Path("reports/output")
    reports_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    csv_path = reports_dir / f"session_{date_str}_{session_id[:8]}.csv"

    with Session() as db_session:
        jobs = _get_session_jobs(session_id, db_session)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Timestamp", "Job Title", "Company", "Location",
                "Status", "ATS Platform", "Apply Site",
                "Application ID", "Job URL", "Note",
            ])
            for j in jobs:
                writer.writerow([
                    j.timestamp, j.job_title, j.company, j.location,
                    j.status, j.ats_platform, j.apply_site,
                    j.application_id, j.job_url, j.note,
                ])

    logger.info(f"CSV report written: {csv_path}")
    return str(csv_path)


def generate_html_summary(session_id: str, stats: dict) -> str:
    """
    Render an HTML summary report for emailing.
    Returns the HTML string.
    """
    from config import settings
    from db.models import get_engine, get_session_factory

    template_path = Path("reports/templates/summary.html")
    if not template_path.exists():
        logger.warning("summary.html template not found — using plain fallback")
        return _plain_fallback(stats)

    engine = get_engine(settings.db_path)
    Session = get_session_factory(engine)

    with Session() as db_session:
        jobs = _get_session_jobs(session_id, db_session)

    rows_html = ""
    for j in jobs:
        color = {"applied": "#c6f6d5", "failed": "#fed7d7", "skipped": "#fefcbf",
                 "duplicate": "#e2e8f0"}.get(j.status, "#fff")
        rows_html += (
            f"<tr style='background:{color}'>"
            f"<td>{j.job_title}</td><td>{j.company}</td>"
            f"<td>{j.status}</td><td>{j.apply_site}</td>"
            f"<td>{j.application_id or '—'}</td></tr>"
        )

    template = template_path.read_text()
    html = (
        template
        .replace("{{total_applied}}", str(stats.get("total_applied", 0)))
        .replace("{{total_skipped}}", str(stats.get("total_skipped", 0)))
        .replace("{{total_failed}}", str(stats.get("total_failed", 0)))
        .replace("{{date}}", datetime.utcnow().strftime("%B %d, %Y"))
        .replace("{{job_rows}}", rows_html)
    )
    return html


def _plain_fallback(stats: dict) -> str:
    return (
        f"<p>Applied: {stats.get('total_applied',0)} | "
        f"Skipped: {stats.get('total_skipped',0)} | "
        f"Failed: {stats.get('total_failed',0)}</p>"
    )
