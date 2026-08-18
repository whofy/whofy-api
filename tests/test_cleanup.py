"""
Tests for date/expiry logic in listings/shared/storage.py.

Guards against regressions of the three related date bugs fixed on 2026-08-11:
  - Bug 1 (F-04) — `_is_too_old` must accept both `datetime` and `str` inputs
  - Bug 2 (F-01) — `cleanup_expired_jobs` must use a real datetime cutoff
  - Bug 3 (F-20) — `cleanup_expired_jobs` must gate on `last_seen_at`, not `added_at`
"""

from datetime import datetime, timezone, timedelta

from listings.shared.retention import RETENTION_DAYS
from listings.shared.storage import _is_too_old, cleanup_expired_jobs


# ─────────────────────────────────────────────────────────────
# _is_too_old — accepts str / datetime / None
# ─────────────────────────────────────────────────────────────

def test_is_too_old_string_recent_returns_false():
    """A string ISO timestamp within the age window is NOT too old."""
    recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    assert _is_too_old(recent) is False


def test_is_too_old_string_ancient_returns_true():
    """A string ISO timestamp older than the window IS too old."""
    ancient = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS + 5)).isoformat()
    assert _is_too_old(ancient) is True


def test_is_too_old_datetime_recent_returns_false():
    """Bug 1 regression guard — datetime inputs must be handled, not silently accepted."""
    recent = datetime.now(timezone.utc) - timedelta(days=5)
    assert _is_too_old(recent) is False


def test_is_too_old_datetime_ancient_returns_true():
    """
    Bug 1 regression guard — the old code called `.replace("Z", ...)` on datetime
    inputs, hit TypeError, and returned False (i.e., "not too old"), silently
    letting old jobs in. This test locks that behavior down.
    """
    ancient = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS + 5)
    assert _is_too_old(ancient) is True


def test_is_too_old_none_returns_false():
    """Missing dates are treated as 'unknown, keep' — not 'old, drop'."""
    assert _is_too_old(None) is False
    assert _is_too_old("") is False


def test_is_too_old_malformed_string_returns_false():
    """Garbage strings should not crash — degrade to 'keep'."""
    assert _is_too_old("not-a-date") is False


def test_is_too_old_naive_datetime_treated_as_utc():
    """A naive datetime (no tzinfo) should be interpreted as UTC, not crash."""
    naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)
    assert naive.tzinfo is None
    assert _is_too_old(naive) is False


# ─────────────────────────────────────────────────────────────
# cleanup_expired_jobs — must delete by last_seen_at with datetime cutoff
# ─────────────────────────────────────────────────────────────

def test_cleanup_deletes_jobs_last_seen_beyond_window(mock_sync_db):
    """Jobs whose last_seen_at is older than RETENTION_DAYS get deleted."""
    now = datetime.now(timezone.utc)
    mock_sync_db.jobs.insert_many([
        {"_id": "stale-1", "last_seen_at": now - timedelta(days=RETENTION_DAYS + 1)},
        {"_id": "stale-2", "last_seen_at": now - timedelta(days=RETENTION_DAYS + 30)},
        {"_id": "fresh-1", "last_seen_at": now - timedelta(days=5)},
        {"_id": "fresh-2", "last_seen_at": now},
    ])

    deleted = cleanup_expired_jobs()
    assert deleted == 2

    remaining_ids = {d["_id"] for d in mock_sync_db.jobs.find({}, {"_id": 1})}
    assert remaining_ids == {"fresh-1", "fresh-2"}


def test_cleanup_uses_datetime_cutoff_not_string(mock_sync_db):
    """
    Bug 2 regression guard — the old code passed `.isoformat()` (a string)
    to `$lt`, which mostly failed to match BSON dates and deleted nothing.
    This test asserts the query actually matches datetime-typed fields.
    """
    old_dt = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS + 10)
    mock_sync_db.jobs.insert_one({"_id": "old", "last_seen_at": old_dt})
    deleted = cleanup_expired_jobs()
    assert deleted == 1


def test_cleanup_keeps_fresh_job_with_old_added_at(mock_sync_db):
    """
    Bug 3 regression guard — a job first ingested 40 days ago but seen on
    the source today (fresh last_seen_at) must NOT be deleted. The old
    code deleted by added_at and would have wrongly removed this.
    """
    now = datetime.now(timezone.utc)
    mock_sync_db.jobs.insert_one({
        "_id": "long-lived",
        "added_at": now - timedelta(days=40),
        "last_seen_at": now,
    })
    deleted = cleanup_expired_jobs()
    assert deleted == 0
    assert mock_sync_db.jobs.count_documents({"_id": "long-lived"}) == 1
