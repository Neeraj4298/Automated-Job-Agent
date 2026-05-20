"""
tests/test_db.py — Tests for database models, CRUD operations, and deduplication.
"""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, AppliedJob, JobQueue
from db.crud import (
    make_dedup_key,
    job_exists,
    insert_job,
    update_job_status,
    add_to_queue,
    get_pending_jobs,
    increment_retry,
)


@pytest.fixture
def db_session():
    """In-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ── make_dedup_key ─────────────────────────────────────────────────────────

def test_dedup_key_is_deterministic():
    key1 = make_dedup_key("https://example.com/job/123", "Acme Corp", "Software Engineer")
    key2 = make_dedup_key("https://example.com/job/123", "Acme Corp", "Software Engineer")
    assert key1 == key2


def test_dedup_key_is_case_insensitive():
    key1 = make_dedup_key("https://EXAMPLE.COM/job/123", "ACME corp", "software engineer")
    key2 = make_dedup_key("https://example.com/job/123", "Acme Corp", "Software Engineer")
    assert key1 == key2


def test_dedup_key_differs_for_different_jobs():
    key1 = make_dedup_key("https://example.com/job/1", "Acme", "Engineer")
    key2 = make_dedup_key("https://example.com/job/2", "Acme", "Engineer")
    assert key1 != key2


def test_dedup_key_length_is_64():
    key = make_dedup_key("https://example.com", "Company", "Role")
    assert len(key) == 64


# ── job_exists + insert_job ────────────────────────────────────────────────

def test_job_does_not_exist_initially(db_session):
    job_id = make_dedup_key("https://example.com/job/1", "Acme", "Engineer")
    assert not job_exists(db_session, job_id)


def test_insert_and_check_exists(db_session):
    job_id = make_dedup_key("https://example.com/job/1", "Acme", "Engineer")
    insert_job(db_session, {
        "id": job_id,
        "job_title": "Engineer",
        "company": "Acme",
        "job_url": "https://example.com/job/1",
        "apply_site": "example.com",
        "status": "applied",
        "timestamp": datetime.utcnow(),
        "retry_count": 0,
    })
    assert job_exists(db_session, job_id)


def test_insert_three_records_and_check_all(db_session):
    fake_jobs = [
        ("https://a.com/1", "CompanyA", "Dev I"),
        ("https://b.com/2", "CompanyB", "Analyst"),
        ("https://c.com/3", "CompanyC", "ML Eng"),
    ]
    ids = []
    for url, co, title in fake_jobs:
        jid = make_dedup_key(url, co, title)
        ids.append(jid)
        insert_job(db_session, {
            "id": jid, "job_title": title, "company": co,
            "job_url": url, "apply_site": "test.com",
            "status": "applied", "timestamp": datetime.utcnow(), "retry_count": 0,
        })
    for jid in ids:
        assert job_exists(db_session, jid)


def test_duplicate_insert_does_not_raise(db_session):
    job_id = make_dedup_key("https://example.com/job/1", "Acme", "Eng")
    record = {"id": job_id, "job_title": "Eng", "company": "Acme",
              "job_url": "https://example.com/job/1", "apply_site": "example.com",
              "status": "applied", "timestamp": datetime.utcnow(), "retry_count": 0}
    insert_job(db_session, record)
    insert_job(db_session, record)   # Should not raise
    count = db_session.query(AppliedJob).filter_by(id=job_id).count()
    assert count == 1


# ── update_job_status ──────────────────────────────────────────────────────

def test_update_job_status(db_session):
    job_id = make_dedup_key("https://x.com/job", "X Corp", "Tester")
    insert_job(db_session, {
        "id": job_id, "job_title": "Tester", "company": "X Corp",
        "job_url": "https://x.com/job", "apply_site": "x.com",
        "status": "applied", "timestamp": datetime.utcnow(), "retry_count": 0,
    })
    update_job_status(db_session, job_id, "unconfirmed", note="No confirmation screen")
    record = db_session.query(AppliedJob).filter_by(id=job_id).first()
    assert record.status == "unconfirmed"
    assert record.note == "No confirmation screen"


# ── increment_retry ────────────────────────────────────────────────────────

def test_increment_retry(db_session):
    job_id = make_dedup_key("https://y.com/job", "Y Corp", "Dev")
    insert_job(db_session, {
        "id": job_id, "job_title": "Dev", "company": "Y Corp",
        "job_url": "https://y.com/job", "apply_site": "y.com",
        "status": "failed", "timestamp": datetime.utcnow(), "retry_count": 0,
    })
    count = increment_retry(db_session, job_id)
    assert count == 1
    count = increment_retry(db_session, job_id)
    assert count == 2


# ── job_queue ──────────────────────────────────────────────────────────────

def test_add_to_queue_and_get_pending(db_session):
    job_id = make_dedup_key("https://z.com/job", "Z Inc", "Analyst")
    add_to_queue(db_session, {
        "id": job_id, "job_url": "https://z.com/job",
        "job_title": "Analyst", "company": "Z Inc", "apply_site": "z.com",
    })
    pending = get_pending_jobs(db_session, limit=10)
    assert any(j.id == job_id for j in pending)


def test_queue_skips_already_applied(db_session):
    job_id = make_dedup_key("https://a.com/job", "A Corp", "Dev")
    insert_job(db_session, {
        "id": job_id, "job_title": "Dev", "company": "A Corp",
        "job_url": "https://a.com/job", "apply_site": "a.com",
        "status": "applied", "timestamp": datetime.utcnow(), "retry_count": 0,
    })
    add_to_queue(db_session, {
        "id": job_id, "job_url": "https://a.com/job",
        "job_title": "Dev", "company": "A Corp", "apply_site": "a.com",
    })
    queue_count = db_session.query(JobQueue).filter_by(id=job_id).count()
    assert queue_count == 0
