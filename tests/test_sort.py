"""Tests for server-side sort on /api/matches and /api/search.

The Company (A–Z) sort was previously client-side only, applied to the 15
rows on the current page. Page 2 then restarted the alphabet — a real bug.
Now the server orders the full result set, so pagination stays consistent.
"""
from datetime import datetime, timezone, timedelta

import pytest


def _make_doc(company, title="Engineer", days_ago=0, work_type="Remote",
              experience="Senior", description=""):
    now = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "source": "greenhouse",
        "source_job_id": f"gh_{company}_{title}",
        "title": title,
        "company": company,
        "location": "Remote",
        "apply_url": f"https://example.com/{company}",
        "fingerprint": f"fp_{company}_{title}",
        "posted_at": now,
        "added_at": now,
        "last_seen_at": now,
        "description": description or f"{title} at {company}",
        "required_skills": ["Python"],
        "work_type": work_type,
        "experience_level": experience,
        "lang_checked": True,
    }


@pytest.fixture
async def _seeded(mock_async_db):
    """Seed a mix of companies out of alphabetical order so a real sort
    is observable, and vary posted_at so 'newest' produces a distinct
    order from 'company'."""
    docs = [
        _make_doc("Zephyr Labs",  days_ago=7),   # newest? no
        _make_doc("Acme Corp",    days_ago=0),   # newest
        _make_doc("MongoDB",      days_ago=3),
        _make_doc("Bloom",        days_ago=5),
        _make_doc("Palantir",     days_ago=1),
    ]
    await mock_async_db.jobs.insert_many(docs)
    return mock_async_db


@pytest.mark.asyncio
async def test_matches_default_sort_is_newest_when_no_skills(client, _seeded):
    resp = client.get("/api/matches").json()
    companies = [j["company"] for j in resp["jobs"]]
    # Newest first: Acme (0d) → Palantir (1d) → MongoDB (3d) → Bloom (5d) → Zephyr (7d)
    assert companies == ["Acme Corp", "Palantir", "MongoDB", "Bloom", "Zephyr Labs"]


@pytest.mark.asyncio
async def test_matches_sort_company_is_alphabetical(client, _seeded):
    resp = client.get("/api/matches?sort=company").json()
    companies = [j["company"] for j in resp["jobs"]]
    assert companies == ["Acme Corp", "Bloom", "MongoDB", "Palantir", "Zephyr Labs"]


@pytest.mark.asyncio
async def test_matches_sort_company_is_stable_across_pages(client, _seeded):
    """The whole point of this fix: page 2 continues the alphabet, does
    not restart it."""
    page1 = client.get("/api/matches?sort=company&limit=2&skip=0").json()
    page2 = client.get("/api/matches?sort=company&limit=2&skip=2").json()
    page3 = client.get("/api/matches?sort=company&limit=2&skip=4").json()

    seq = [j["company"] for j in page1["jobs"] + page2["jobs"] + page3["jobs"]]
    assert seq == ["Acme Corp", "Bloom", "MongoDB", "Palantir", "Zephyr Labs"]


@pytest.mark.asyncio
async def test_matches_sort_newest_explicit_overrides_default(client, _seeded):
    resp = client.get("/api/matches?sort=newest").json()
    companies = [j["company"] for j in resp["jobs"]]
    assert companies[0] == "Acme Corp"
    assert companies[-1] == "Zephyr Labs"


@pytest.mark.asyncio
async def test_matches_unknown_sort_falls_back_to_newest(client, _seeded):
    """Defence: garbage `?sort=foo` should not 500 or produce an empty result."""
    resp = client.get("/api/matches?sort=foo").json()
    assert len(resp["jobs"]) == 5
    assert resp["jobs"][0]["company"] == "Acme Corp"


# NOTE: `/api/search` uses MongoDB's $text operator which mongomock does
# not implement — so the search-branch sort override cannot be tested here
# without spinning up a real Mongo. The code path is identical to the
# /api/matches with-skills branch (both call _resolve_agg_sort with the
# endpoint's default), which IS covered by test_matches_sort_company_*.
