"""
db/crud.py — Database read/write helpers.

All public functions accept a SQLAlchemy Session so they are
testable without touching the filesystem.
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from db.models import AppliedJob, JobQueue, SessionLog


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication
# ─────────────────────────────────────────────────────────────────────────────

def make_dedup_key(url: str, company: str, title: str) -> str:
    """
    Create a deterministic SHA-256 key from the job's URL, company, and title.
    Used as the primary key in both applied_jobs and job_queue tables.
    """
    raw = f"{url.strip().lower()}{company.strip().lower()}{title.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Applied Jobs
# ─────────────────────────────────────────────────────────────────────────────

def job_exists(session: Session, job_id: str) -> bool:
    """Return True if a job with this ID has already been applied to."""
    return session.query(AppliedJob).filter_by(id=job_id).count() > 0


def insert_job(session: Session, job_data: Dict) -> AppliedJob:
    """
    Insert a new job application record.  'job_data' must include at least:
      id, job_title, company, job_url, status
    """
    record = AppliedJob(**job_data)
    session.merge(record)       # merge = insert-or-update (idempotent)
    session.commit()
    logger.debug("Inserted job record.")
    return record


def update_job_status(
    session: Session,
    job_id: str,
    status: str,
    note: str = "",
    application_id: str = "",
) -> None:
    """Update the status and optional fields of an existing job record."""
    record = session.query(AppliedJob).filter_by(id=job_id).first()
    if not record:
        logger.warning("update_job_status: job not found")
        return
    record.status = status
    if note:
        record.note = note
    if application_id:
        record.application_id = application_id
    session.commit()


def increment_retry(session: Session, job_id: str) -> int:
    """Increment retry_count and return the new value."""
    record = session.query(AppliedJob).filter_by(id=job_id).first()
    if not record:
        return 0
    record.retry_count += 1
    session.commit()
    return record.retry_count


def get_domain_count(session: Session, domain: str, since_hours: int = 24) -> int:
    """Return how many applications were made to a domain in the last N hours."""
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    return (
        session.query(AppliedJob)
        .filter(AppliedJob.apply_site == domain)
        .filter(AppliedJob.timestamp >= cutoff)
        .filter(AppliedJob.status == "applied")
        .count()
    )


def get_session_total(session: Session, session_id: str) -> int:
    """Return total applied count that reference this session (via note field)."""
    # We use the start_time of the session as a proxy window
    log = session.query(SessionLog).filter_by(session_id=session_id).first()
    if not log or not log.start_time:
        return 0
    return (
        session.query(AppliedJob)
        .filter(AppliedJob.timestamp >= log.start_time)
        .filter(AppliedJob.status == "applied")
        .count()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Job Queue
# ─────────────────────────────────────────────────────────────────────────────

def add_to_queue(session: Session, job: Dict, scheduled_date: Optional[datetime] = None) -> None:
    """Add a job to the queue if not already queued or applied."""
    job_id = job["id"]
    if job_exists(session, job_id):
        logger.debug("Queue skip: already applied")
        return
    existing = session.query(JobQueue).filter_by(id=job_id).first()
    if existing:
        logger.debug("Queue skip: already queued")
        return
    entry = JobQueue(
        id=job_id,
        job_url=job.get("job_url", ""),
        job_title=job.get("job_title", ""),
        company=job.get("company", ""),
        apply_site=job.get("apply_site", ""),
        priority=job.get("priority", 5),
        scheduled_date=scheduled_date or datetime.utcnow(),
    )
    session.add(entry)
    session.commit()


def get_pending_jobs(session: Session, limit: int = 100) -> List[JobQueue]:
    """Return pending queue items scheduled for today or earlier, ordered by priority."""
    now = datetime.utcnow()
    return (
        session.query(JobQueue)
        .filter(JobQueue.status == "pending")
        .filter(JobQueue.scheduled_date <= now)
        .order_by(JobQueue.priority.asc(), JobQueue.added_date.asc())
        .limit(limit)
        .all()
    )


def mark_queue_done(session: Session, job_id: str) -> None:
    entry = session.query(JobQueue).filter_by(id=job_id).first()
    if entry:
        entry.status = "done"
        session.commit()


def mark_queue_failed(session: Session, job_id: str) -> None:
    entry = session.query(JobQueue).filter_by(id=job_id).first()
    if entry:
        entry.status = "failed"
        session.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Session Log
# ─────────────────────────────────────────────────────────────────────────────

def create_session_log(session: Session) -> str:
    """Create a new session log entry and return the session_id."""
    session_id = str(uuid.uuid4())
    log = SessionLog(
        session_id=session_id,
        start_time=datetime.utcnow(),
        sites_blocked=json.dumps([]),
        alerts_sent=json.dumps([]),
    )
    session.add(log)
    session.commit()
    logger.info("Session started.")
    return session_id


def update_session_log(
    session: Session,
    session_id: str,
    total_applied: int = 0,
    total_skipped: int = 0,
    total_failed: int = 0,
    sites_blocked: Optional[List[str]] = None,
    alerts_sent: Optional[List[str]] = None,
) -> None:
    """Update session statistics (call this incrementally or at end of session)."""
    log = session.query(SessionLog).filter_by(session_id=session_id).first()
    if not log:
        logger.error("Session log not found.")
        return
    log.end_time = datetime.utcnow()
    log.total_applied = total_applied
    log.total_skipped = total_skipped
    log.total_failed = total_failed
    if sites_blocked is not None:
        log.sites_blocked = json.dumps(sites_blocked)
    if alerts_sent is not None:
        log.alerts_sent = json.dumps(alerts_sent)
    session.commit()
