"""Regression guards for pipeline/dedupe_jobs.py (C-03).

canonical_fingerprint is normalized(company + title + location). It carries
no notion of *which posting* a row is, so grouping on it alone treated
genuinely distinct requisitions as duplicates:

  A large employer routinely has several open roles with the same title in
  the same location — different teams, different reqs, different apply URLs.
  On one board those are separate jobs with separate source_job_ids. The old
  grouping deleted all but one of them, every night, re-deleting them after
  each ingestion re-added them.

Dedup is now cross-source only: a group must span 2+ sources, and only rows
from the losing sources are removed.
"""
from datetime import datetime, timezone

import pytest

from pipeline.dedupe_jobs import dedupe


FP = "acme||softwareengineer||bengaluruindia"


def _row(source, source_job_id, fingerprint=FP, last_seen_at=None):
    return {
        "source": source,
        "source_job_id": source_job_id,
        "canonical_fingerprint": fingerprint,
        "company": "Acme",
        "title": "Software Engineer",
        "location": "Bengaluru, India",
        "last_seen_at": last_seen_at or datetime.now(timezone.utc),
    }


def test_distinct_requisitions_from_one_source_are_never_deleted(mock_sync_db):
    """Three separate Greenhouse reqs, same title/location — all must survive."""
    mock_sync_db.jobs.insert_many([
        _row("greenhouse", "gh_1"),
        _row("greenhouse", "gh_2"),
        _row("greenhouse", "gh_3"),
    ])

    groups, deleted = dedupe(mock_sync_db)

    assert deleted == 0
    assert mock_sync_db.jobs.count_documents({}) == 3


def test_same_job_on_two_sources_collapses_to_the_preferred_source(mock_sync_db):
    """Greenhouse outranks Ashby, so the Ashby copy goes."""
    mock_sync_db.jobs.insert_many([
        _row("greenhouse", "gh_1"),
        _row("ashby", "ash_1"),
    ])

    groups, deleted = dedupe(mock_sync_db)

    assert groups == 1
    assert deleted == 1
    remaining = list(mock_sync_db.jobs.find({}))
    assert len(remaining) == 1
    assert remaining[0]["source"] == "greenhouse"


def test_cross_source_dedup_keeps_all_rows_of_the_winning_source(mock_sync_db):
    """
    The combined case, and the one the old code got wrong: two distinct
    Greenhouse reqs plus one Ashby duplicate. Only the Ashby row is redundant
    — both Greenhouse rows are real, separate jobs.
    """
    mock_sync_db.jobs.insert_many([
        _row("greenhouse", "gh_1"),
        _row("greenhouse", "gh_2"),
        _row("ashby", "ash_1"),
    ])

    groups, deleted = dedupe(mock_sync_db)

    assert deleted == 1
    survivors = {d["source"] for d in mock_sync_db.jobs.find({})}
    assert survivors == {"greenhouse"}
    assert mock_sync_db.jobs.count_documents({}) == 2


def test_different_fingerprints_are_left_alone(mock_sync_db):
    """Different company/title/location — not duplicates by any definition."""
    mock_sync_db.jobs.insert_many([
        _row("greenhouse", "gh_1", fingerprint="acme||engineer||london"),
        _row("ashby", "ash_1", fingerprint="other||designer||berlin"),
    ])

    groups, deleted = dedupe(mock_sync_db)

    assert groups == 0
    assert deleted == 0
    assert mock_sync_db.jobs.count_documents({}) == 2


def test_dry_run_reports_without_deleting(mock_sync_db):
    """--dry-run must leave the collection untouched."""
    mock_sync_db.jobs.insert_many([
        _row("greenhouse", "gh_1"),
        _row("ashby", "ash_1"),
    ])

    groups, deleted = dedupe(mock_sync_db, dry_run=True)

    assert groups == 1
    assert deleted == 0
    assert mock_sync_db.jobs.count_documents({}) == 2
