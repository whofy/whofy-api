"""Tests for the location-tokens indexing path.

Ingest stores `location_tokens` — a lowercase array split from the raw
`location` string. Queries hit that array with $all, an indexed lookup
that replaced the previous unindexed case-insensitive regex.
"""
from datetime import datetime, timezone, timedelta

import pytest

from listings.shared.storage import _tokenize_location, save_jobs


# ── Pure tokenization ─────────────────────────────────────────────

def test_tokenize_empty():
    assert _tokenize_location("") == []
    assert _tokenize_location(None) == []


def test_tokenize_single_city_country():
    assert _tokenize_location("Bengaluru, India") == ["bengaluru", "india"]


def test_tokenize_semicolon_multi_location():
    assert _tokenize_location("Berlin, Germany; London, United Kingdom") == [
        "berlin", "germany", "london", "united kingdom"
    ]


def test_tokenize_dedupes():
    """A job listed as "New York, USA; NY, USA" shouldn't have "usa" twice."""
    assert _tokenize_location("New York, USA; NY, USA") == ["new york", "usa", "ny"]


def test_tokenize_preserves_multiword_tokens():
    """'United Kingdom' is ONE token — splitting it on the space would
    make user picks like "Kingdom" match false positives."""
    assert "united kingdom" in _tokenize_location("London, United Kingdom")


def test_tokenize_remote():
    assert _tokenize_location("Remote") == ["remote"]


# ── Ingest writes tokens on every job ─────────────────────────────

def _raw_job(location):
    return {
        "source": "greenhouse",
        "source_job_id": f"gh_{location.replace(' ', '_')}",
        "title": "Software Engineer",
        "company": "Acme Corp",
        "location": location,
        "apply_url": "https://example.com/x",
        "description": "Backend role.",
        "required_skills": ["Python"],
        "work_type": "Remote",
        "experience_level": "Senior",
        "lang_checked": True,
        "posted_at": datetime.now(timezone.utc) - timedelta(days=1),
    }


def test_save_jobs_writes_location_tokens_on_every_doc(mock_sync_db):
    save_jobs([_raw_job("Bengaluru, India"), _raw_job("Remote")], source="greenhouse")

    docs = list(mock_sync_db.jobs.find({}, {"location_tokens": 1, "location": 1}))
    assert len(docs) == 2
    for doc in docs:
        assert isinstance(doc.get("location_tokens"), list), (
            "Every ingested job must carry location_tokens — the filter's "
            "fast path depends on it. Missing field means the doc silently "
            "falls through to the legacy regex fallback."
        )
        assert len(doc["location_tokens"]) > 0


def test_index_declaration_uses_correct_field(mock_sync_db):
    """Guard: ensure_indexes declares an index on location_tokens. Without
    it, the $all query goes back to a full-collection scan."""
    from listings.shared.storage import ensure_indexes
    ensure_indexes()

    indexes = mock_sync_db.jobs.index_information()
    indexed_fields = {k for idx in indexes.values() for k, _ in idx["key"]}
    assert "location_tokens" in indexed_fields, "missing index — filter will COLLSCAN"
    assert "source" in indexed_fields, "missing index — source filter will COLLSCAN"
