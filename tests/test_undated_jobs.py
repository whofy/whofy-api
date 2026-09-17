"""Regression guards for jobs that carry no posting date.

Undated jobs are a supported, normal case — Lever exposes no post date at
all, and Workday hands us human strings ("Posted 5 Days Ago") that don't
always parse. Two separate bugs punished them:

  C-01  Workday wrote "" instead of None for an unparseable date. Job.posted_at
        is Optional[datetime]; "" is neither, so validation rejected the whole
        job and it silently landed in ingestion_rejections.

  C-02  save_jobs' source-cap sort used `j.get("posted_at") or ""`, which
        substituted a str for None and then asked Python to order a datetime
        against a str — TypeError, which failed the entire source and (because
        run_ingestion skips cleanup when any source fails) took retention
        enforcement down with it.
"""
from datetime import datetime, timedelta, timezone

from models.job import Job
from listings.shared.storage import save_jobs, _posted_sort_key


def _job_dict(**overrides):
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
# C-01 — empty-string posting dates must not drop the job
# ─────────────────────────────────────────────────────────────

def test_empty_string_posted_at_normalizes_to_none_not_validation_error():
    """An empty date string means "undated", not "invalid job"."""
    job = Job.model_validate({
        "source": "workday",
        "source_job_id": "wd_acme_123",
        "title": "Backend Engineer",
        "company": "Acme",
        "location": "Remote",
        "apply_url": "https://example.com/apply",
        "fingerprint": "workdaywd_acme_123",
        "posted_at": "",
        "added_at": datetime.now(timezone.utc),
        "last_seen_at": datetime.now(timezone.utc),
        "required_skills": [],
        "work_type": "Remote",
        "experience_level": "Mid Level",
        "lang_checked": True,
    })
    assert job.posted_at is None


def test_workday_undated_listing_is_saved_not_schema_rejected(mock_sync_db):
    """A Workday row whose postedOn didn't parse must reach the database."""
    result = save_jobs([_job_dict(posted_at=None)], source="workday")

    assert result["schema_rejected"] == 0
    assert mock_sync_db.jobs.count_documents({}) == 1
    assert mock_sync_db.jobs.find_one({})["posted_at"] is None


def test_workday_fetcher_emits_none_for_unparseable_date():
    """The fetcher itself must not produce "" — that was the original bug."""
    from listings.scraping.workday.fetcher import _parse_posted_age

    # Nothing in this string looks like an age, so the parser gives up.
    assert _parse_posted_age("Posted sometime last quarter") is None


# ─────────────────────────────────────────────────────────────
# C-02 — the source-cap sort must survive mixed date types
# ─────────────────────────────────────────────────────────────

def test_cap_sort_key_handles_datetime_isostring_and_none():
    """posted_at reaches this sort before Pydantic coerces it, so all three
    shapes are live: datetime, ISO string, and None."""
    now = datetime.now(timezone.utc)

    assert _posted_sort_key({"posted_at": now}) == now
    assert _posted_sort_key({"posted_at": now.isoformat()}) == now
    assert _posted_sort_key({"posted_at": None}) < now
    assert _posted_sort_key({}) < now
    # Unparseable strings sort last rather than raising.
    assert _posted_sort_key({"posted_at": "not a date"}) < now


def test_cap_sort_key_treats_naive_datetime_as_utc():
    """Comparing naive against aware datetimes raises — normalize first."""
    naive = datetime(2026, 1, 1, 12, 0, 0)
    assert _posted_sort_key({"posted_at": naive}).tzinfo is not None


def test_save_jobs_cap_with_mixed_dated_and_undated_does_not_raise(mock_sync_db):
    """
    The original failure mode: sorted() comparing datetime against "" for the
    undated rows raised TypeError, which failed the whole source.
    """
    now = datetime.now(timezone.utc)
    jobs = [
        _job_dict(source_job_id=f"dated_{i}", posted_at=now - timedelta(days=i))
        for i in range(5)
    ] + [
        _job_dict(source_job_id=f"undated_{i}", posted_at=None)
        for i in range(5)
    ]

    result = save_jobs(jobs, source="test_src", cap=5)

    assert result["capped"] is True
    assert mock_sync_db.jobs.count_documents({}) == 5


def test_cap_keeps_newest_and_drops_undated_first(mock_sync_db):
    """Undated jobs sort last, so under pressure the dated ones win."""
    now = datetime.now(timezone.utc)
    jobs = [
        _job_dict(source_job_id="fresh", posted_at=now),
        _job_dict(source_job_id="older", posted_at=now - timedelta(days=3)),
        _job_dict(source_job_id="undated", posted_at=None),
    ]

    save_jobs(jobs, source="test_src", cap=2)

    kept = {d["source_job_id"] for d in mock_sync_db.jobs.find({})}
    assert kept == {"fresh", "older"}
