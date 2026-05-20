"""
db/models.py — SQLAlchemy ORM models for the job application system.

Tables:
  - applied_jobs   : Full record for every application attempted
  - job_queue      : Prioritised queue of jobs yet to be applied to
  - session_log    : Per-scheduler-run statistics
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


class AppliedJob(Base):
    """
    One row per job application attempt.
    Primary key is a SHA-256 hash of (url + company + title) so duplicate
    runs produce the same key and the INSERT is idempotent.
    """

    __tablename__ = "applied_jobs"

    id = Column(String(64), primary_key=True)       # SHA-256 hex digest
    timestamp = Column(DateTime, default=datetime.utcnow)
    job_title = Column(String(255))
    company = Column(String(255))
    location = Column(String(255))
    posted_date = Column(String(64))
    job_url = Column(Text)
    apply_site = Column(String(128))                # e.g. "linkedin.com"
    ats_platform = Column(String(64))               # Workday / Taleo / Generic…
    status = Column(String(32))                     # applied|failed|skipped|duplicate|blocked|unconfirmed
    note = Column(Text)
    screenshot_path = Column(Text)
    resume_version = Column(String(128))
    cover_letter = Column(Text)
    application_id = Column(String(255))            # Confirmation ID from site
    retry_count = Column(Integer, default=0)


class JobQueue(Base):
    """
    Jobs discovered by the search node that haven't been applied yet.
    Overflow jobs are dated to the next day so the scheduler picks them up.
    """

    __tablename__ = "job_queue"

    id = Column(String(64), primary_key=True)       # Same SHA-256 scheme
    job_url = Column(Text)
    job_title = Column(String(255))
    company = Column(String(255))
    apply_site = Column(String(128))
    priority = Column(Integer, default=5)           # Lower = higher priority
    added_date = Column(DateTime, default=datetime.utcnow)
    scheduled_date = Column(DateTime)               # Apply on/after this date
    status = Column(String(32), default="pending")  # pending|processing|done|failed


class SessionLog(Base):
    """
    One row per scheduler run (one run = one daily session).
    """

    __tablename__ = "session_log"

    session_id = Column(String(64), primary_key=True)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    total_applied = Column(Integer, default=0)
    total_skipped = Column(Integer, default=0)
    total_failed = Column(Integer, default=0)
    sites_blocked = Column(Text)                    # JSON list of blocked domains
    alerts_sent = Column(Text)                      # JSON list of alert messages


def get_engine(db_path: str = "applied_jobs.db"):
    """Create (or connect to) the SQLite database and return the engine."""
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    Base.metadata.create_all(engine)
    return engine


def get_session_factory(engine):
    """Return a session factory bound to the given engine."""
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)
