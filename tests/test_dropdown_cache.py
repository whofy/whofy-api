"""Tests for the short-TTL dropdown cache (F-16).

Guards:
  - After caching, adding a new row does NOT show up until TTL expires
    (proves the second call was served from cache).
  - Cache expires after TTL and fresh DB result comes through.
  - Each endpoint has its own cache slot.
"""
import time
from datetime import datetime, timezone

import pytest


@pytest.fixture(autouse=True)
def _clear_cache():
    from fetch_api import jobs as jobs_mod
    jobs_mod._DROPDOWN_CACHE.clear()
    yield
    jobs_mod._DROPDOWN_CACHE.clear()


async def _seed_job(db, company="Acme", location="Bengaluru, India", source="src"):
    now = datetime.now(timezone.utc)
    await db.jobs.insert_one({
        "source": source,
        "source_job_id": f"j_{company}_{location}_{source}",
        "title": "Engineer",
        "company": company,
        "location": location,
        "apply_url": "https://x.com",
        "fingerprint": f"fp_{company}_{location}_{source}",
        "posted_at": now,
        "added_at": now,
        "last_seen_at": now,
        "description": "desc",
    })


@pytest.mark.asyncio
async def test_companies_second_call_returns_cached_stale_data(client, mock_async_db):
    await _seed_job(mock_async_db, company="Acme")
    r1 = client.get("/api/companies").json()
    assert r1 == ["Acme"]

    # Insert a new company after the cache is warmed.
    await _seed_job(mock_async_db, company="Newco", source="src2")

    # Same call within TTL — must still return the OLD list (cached).
    r2 = client.get("/api/companies").json()
    assert r2 == ["Acme"], f"expected stale ['Acme'], got {r2} — cache miss"


@pytest.mark.asyncio
async def test_locations_second_call_returns_cached(client, mock_async_db):
    await _seed_job(mock_async_db, location="Bengaluru, India")
    r1 = client.get("/api/locations").json()
    assert "Bengaluru, India" in r1

    await _seed_job(mock_async_db, location="Mumbai, India", source="s2")
    r2 = client.get("/api/locations").json()
    assert "Mumbai, India" not in r2, "cache miss: fresh location leaked through"


@pytest.mark.asyncio
async def test_sources_second_call_returns_cached(client, mock_async_db):
    await _seed_job(mock_async_db, source="greenhouse")
    r1 = client.get("/api/sources").json()
    assert r1 == ["greenhouse"]

    await _seed_job(mock_async_db, source="lever")
    r2 = client.get("/api/sources").json()
    assert r2 == ["greenhouse"], f"expected stale, got {r2}"


@pytest.mark.asyncio
async def test_cache_expires_after_ttl_and_returns_fresh_data(client, mock_async_db, monkeypatch):
    from fetch_api import jobs as jobs_mod
    monkeypatch.setattr(jobs_mod, "_DROPDOWN_TTL_SECONDS", 0)

    await _seed_job(mock_async_db, company="Acme")
    client.get("/api/companies")

    await _seed_job(mock_async_db, company="Newco", source="s2")
    time.sleep(0.01)

    r2 = client.get("/api/companies").json()
    assert "Newco" in r2, f"TTL=0 should force refetch, got {r2}"


@pytest.mark.asyncio
async def test_endpoints_have_isolated_cache_slots(client, mock_async_db):
    """Calling one endpoint must not populate another's slot."""
    from fetch_api import jobs as jobs_mod

    await _seed_job(mock_async_db, company="Acme")
    client.get("/api/companies")

    assert "companies" in jobs_mod._DROPDOWN_CACHE
    assert "locations" not in jobs_mod._DROPDOWN_CACHE
    assert "sources" not in jobs_mod._DROPDOWN_CACHE
