"""
Tests for save_jobs() and ensure_indexes() in listings/shared/storage.py.

Guards:
  - Upsert dedup: re-scraping same (source, source_job_id) updates, doesn't duplicate
  - added_at set exactly once via $setOnInsert (never overwritten)
  - Fingerprint computed correctly
  - Location normalized before save
  - Too-old jobs filtered out at save time
  - lang_checked forced to True on accepted jobs
  - Schema-invalid jobs counted (F-19 partial regression guard)
  - Source cap truncates to newest N when exceeded
  - ensure_indexes creates the saved_jobs unique index (F-07)
"""

import time
from datetime import datetime, timezone, timedelta

from listings.shared.storage import (
    save_jobs,
    ensure_indexes,
    _fingerprint,
)


def _job_dict(**overrides):
    """Minimal valid job payload accepted by save_jobs → Job model."""
    now = datetime.now(timezone.utc)
    base = {
        "source": "test_src",
        "source_job_id": "abc123",
        "title": "Software Engineer",
        "company": "TestCo",
        "location": "Bengaluru, India",
        "apply_url": "https://example.com/apply",
        "posted_at": now,
        "description": "Great role for Python + React developers.",
        "required_skills": ["Python", "React"],
        "work_type": "Remote",
        "experience_level": "Senior",
        "lang_checked": True,
        "data_quality_flags": [],
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────
# Insert / re-scrape behavior
# ─────────────────────────────────────────────────────────────

def test_save_jobs_inserts_new_job(mock_sync_db):
    result = save_jobs([_job_dict()], source="test_src")
    assert result["upserted"] == 1
    assert mock_sync_db.jobs.count_documents({}) == 1


def test_save_jobs_rescrape_updates_not_duplicates(mock_sync_db):
    """Re-scraping the same (source, source_job_id) must update in place, not insert a duplicate."""
    save_jobs([_job_dict()], source="test_src")
    result = save_jobs([_job_dict(title="Updated Title")], source="test_src")
    assert result["upserted"] == 0
    assert mock_sync_db.jobs.count_documents({}) == 1
    doc = mock_sync_db.jobs.find_one({})
    assert doc["title"] == "Updated Title"


def test_save_jobs_added_at_never_overwritten(mock_sync_db):
    """
    $setOnInsert semantic — added_at is set on the first insert and MUST NOT
    change on subsequent re-scrapes, even though other fields update.
    """
    save_jobs([_job_dict()], source="test_src")
    original_added_at = mock_sync_db.jobs.find_one({})["added_at"]

    time.sleep(0.02)
    save_jobs([_job_dict(title="Updated Again")], source="test_src")
    doc = mock_sync_db.jobs.find_one({})

    assert doc["added_at"] == original_added_at
    assert doc["last_seen_at"] >= original_added_at


# ─────────────────────────────────────────────────────────────
# Derived / normalized fields
# ─────────────────────────────────────────────────────────────

def test_fingerprint_computed_correctly():
    """Fingerprint is `{source}||{source_job_id}` lowercased and stripped to [a-z0-9|]."""
    assert _fingerprint("test_src", "abc123") == "testsrc||abc123"
    assert _fingerprint("Green-House", "GH_9999") == "greenhouse||gh9999"


def test_save_jobs_stores_fingerprint(mock_sync_db):
    save_jobs([_job_dict()], source="test_src")
    doc = mock_sync_db.jobs.find_one({})
    assert doc["fingerprint"] == "testsrc||abc123"


def test_save_jobs_normalizes_location(mock_sync_db):
    """Raw locations get canonicalized (city + country map lookups) before save."""
    save_jobs([_job_dict(location="bengaluru, in")], source="test_src")
    doc = mock_sync_db.jobs.find_one({})
    assert "India" in doc["location"]


def test_save_jobs_forces_lang_checked_true(mock_sync_db):
    """Any accepted job gets lang_checked=True regardless of input value."""
    save_jobs([_job_dict(lang_checked=False)], source="test_src")
    doc = mock_sync_db.jobs.find_one({})
    assert doc["lang_checked"] is True


# ─────────────────────────────────────────────────────────────
# Filters / rejection paths
# ─────────────────────────────────────────────────────────────

def test_save_jobs_skips_too_old(mock_sync_db):
    """Jobs whose posted_at is beyond MAX_AGE_DAYS should be filtered at save time."""
    old = datetime.now(timezone.utc) - timedelta(days=40)
    result = save_jobs([_job_dict(posted_at=old)], source="test_src")
    assert result["too_old_skipped"] == 1
    assert mock_sync_db.jobs.count_documents({}) == 0


def test_save_jobs_counts_schema_rejected(mock_sync_db):
    """
    Jobs failing Pydantic validation get counted, not silently dropped.
    F-19 partial guard — counter exists (full observability is a P2 open item).
    """
    invalid = _job_dict()
    del invalid["title"]  # required field
    result = save_jobs([invalid], source="test_src")
    assert result["schema_rejected"] == 1
    assert mock_sync_db.jobs.count_documents({}) == 0


def test_save_jobs_logs_rejection_payload(mock_sync_db):
    """
    F-19 full: rejected jobs get written to ingestion_rejections with the
    raw payload, error type, and error message so failures are debuggable.
    """
    invalid = _job_dict(source_job_id="reject_xyz")
    del invalid["title"]
    save_jobs([invalid], source="test_src")

    rejections = list(mock_sync_db.ingestion_rejections.find({}))
    assert len(rejections) == 1
    r = rejections[0]
    assert r["source"] == "test_src"
    assert r["source_job_id"] == "reject_xyz"
    assert r["company"] == "TestCo"
    assert r["error_type"] == "ValidationError"
    assert "title" in r["error_message"].lower()
    assert r["raw_payload"]["source_job_id"] == "reject_xyz"
    assert "rejected_at" in r


def test_save_jobs_no_rejection_written_when_all_valid(mock_sync_db):
    """Happy path: no rejections collection writes when every job validates."""
    save_jobs([_job_dict()], source="test_src")
    assert mock_sync_db.ingestion_rejections.count_documents({}) == 0


def test_ensure_indexes_creates_rejections_collection(mock_sync_db):
    """The capped rejections collection should exist after ensure_indexes runs."""
    ensure_indexes()
    assert "ingestion_rejections" in mock_sync_db.list_collection_names()


def test_save_jobs_caps_at_source_cap(mock_sync_db):
    """When jobs > cap, batch is truncated to cap (keeping newest by posted_at)."""
    now = datetime.now(timezone.utc)
    jobs = [
        _job_dict(source_job_id=f"j_{i}", posted_at=now - timedelta(days=i))
        for i in range(10)
    ]
    result = save_jobs(jobs, source="test_src", cap=5)
    assert result["capped"] is True
    assert mock_sync_db.jobs.count_documents({}) == 5


# ─────────────────────────────────────────────────────────────
# ensure_indexes
# ─────────────────────────────────────────────────────────────

def test_ensure_indexes_creates_saved_jobs_unique_index(mock_sync_db):
    """
    F-07 regression guard — ensure_indexes must create the unique compound
    index on saved_jobs(user_id, job_id) that prevents duplicate saves.
    """
    ensure_indexes()
    saved_indexes = mock_sync_db.saved_jobs.index_information()
    # Look for a unique index whose key includes both user_id and job_id
    found_unique = False
    for name, idx in saved_indexes.items():
        keys = [k for k, _ in idx.get("key", [])]
        if idx.get("unique") and set(keys) >= {"user_id", "job_id"}:
            found_unique = True
            break
    assert found_unique, f"Expected unique (user_id, job_id) index; got {list(saved_indexes)}"


def test_ensure_indexes_creates_jobs_unique_source_index(mock_sync_db):
    """Jobs collection must have the unique (source, source_job_id) index for upsert dedup."""
    ensure_indexes()
    job_indexes = mock_sync_db.jobs.index_information()
    found_unique = False
    for name, idx in job_indexes.items():
        keys = [k for k, _ in idx.get("key", [])]
        if idx.get("unique") and set(keys) >= {"source", "source_job_id"}:
            found_unique = True
            break
    assert found_unique, f"Expected unique (source, source_job_id) index; got {list(job_indexes)}"
