"""Guard: `last_seen_at` and `added_at` must be stored as real datetimes,
not ISO strings.

Why this matters
----------------
cleanup_expired_jobs() runs nightly and issues:

    collection.delete_many({"last_seen_at": {"$lt": <datetime cutoff>}})

In BSON sort order every String is less than every Date. So if any job in
the collection has `last_seen_at` stored as a string — even one — the
`$lt` comparison silently matches it. If EVERY job has it as a string,
the query matches every job and cleanup wipes the entire collection.

Historically save_jobs computed `now = datetime.now(timezone.utc).isoformat()`
and passed that string to Mongo. It only worked because Pydantic (invoked
inside save_jobs via `Job.model_validate`) coerces ISO strings into real
datetime objects before the write. That coercion is a side effect of a
library the code around it isn't visibly relying on — an easy dependency
to break during a refactor. This test pins the invariant so a regression
fires immediately, instead of a nightly cleanup deleting production data.
"""
from datetime import datetime, timezone, timedelta

import pytest

from listings.shared.storage import save_jobs, cleanup_expired_jobs


def _fresh_raw_job(source="greenhouse", source_job_id="gh_1"):
    """A raw job dict, exactly the shape a fetcher produces before enrichment."""
    return {
        "source": source,
        "source_job_id": source_job_id,
        "title": "Software Engineer",
        "company": "Acme Corp",
        "location": "Remote",
        "apply_url": "https://example.com/1",
        "description": "Backend role using Python and Postgres.",
        # Fields normally populated by enrich, provided here so schema validation passes.
        "required_skills": ["Python", "PostgreSQL"],
        "work_type": "Remote",
        "experience_level": "Senior",
        "lang_checked": True,
        "posted_at": datetime.now(timezone.utc) - timedelta(days=1),
    }


def test_last_seen_at_stored_as_datetime_not_string(mock_sync_db):
    save_jobs([_fresh_raw_job()], source="greenhouse")

    doc = mock_sync_db.jobs.find_one({})
    assert doc is not None, "save_jobs did not persist the job"
    assert isinstance(doc["last_seen_at"], datetime), (
        f"last_seen_at must be datetime, got {type(doc['last_seen_at']).__name__}. "
        "A string here would let cleanup_expired_jobs delete the whole collection "
        "(BSON: every String is less than every Date under $lt)."
    )


def test_added_at_stored_as_datetime_not_string(mock_sync_db):
    save_jobs([_fresh_raw_job()], source="greenhouse")

    doc = mock_sync_db.jobs.find_one({})
    assert isinstance(doc["added_at"], datetime), (
        f"added_at must be datetime, got {type(doc['added_at']).__name__}"
    )


def test_repeated_save_updates_last_seen_but_preserves_added(mock_sync_db):
    """Second sighting of the same job should refresh last_seen_at but
    NOT overwrite added_at — and both must stay datetime-typed through
    the update path, not only the initial insert."""
    save_jobs([_fresh_raw_job()], source="greenhouse")
    first = mock_sync_db.jobs.find_one({})
    original_added_at = first["added_at"]

    # Same source + source_job_id → upsert path (matches on the unique
    # (source, source_job_id) index rather than inserting a new row).
    save_jobs([_fresh_raw_job()], source="greenhouse")
    second = mock_sync_db.jobs.find_one({})

    assert mock_sync_db.jobs.count_documents({}) == 1, "expected upsert, got a duplicate row"
    assert second["added_at"] == original_added_at, "added_at must not be overwritten on re-save"
    assert isinstance(second["added_at"], datetime), "added_at drifted to non-datetime on update"
    assert isinstance(second["last_seen_at"], datetime), "last_seen_at drifted to non-datetime on update"
    assert second["last_seen_at"] >= original_added_at
