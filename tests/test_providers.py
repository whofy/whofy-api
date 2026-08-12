"""
Per-source parse-contract tests for each fetcher in listings/*.

Each test feeds a synthetic payload that matches the source's current API shape
to the fetcher's HTTP call, then asserts the fetcher produces our canonical Job
dict shape. Catches the most common regression class — someone edits a fetcher
and breaks the parse mapping (typo, removed field, wrong key).

Not tested here:
  - Actual upstream API drift (fixtures are frozen; drift is caught by daily
    ingestion + schema_rejected counts, not by these tests).
  - LinkedIn — currently disabled in run_scrapper.py.
  - HackerNews — parses HN thread comments, better tested via _parse_header
    alone (see test_hackernews_header_parser).
"""

import responses

from datetime import datetime


REQUIRED_KEYS = {"source", "source_job_id", "title", "company", "location", "apply_url"}


def _assert_canonical_shape(jobs, expected_source):
    """Every fetcher must produce jobs conforming to the canonical schema."""
    assert isinstance(jobs, list)
    assert len(jobs) > 0
    for job in jobs:
        missing = REQUIRED_KEYS - job.keys()
        assert not missing, f"Missing required keys: {missing}"
        assert job["source"] == expected_source
        assert job["source_job_id"]  # non-empty
        assert job["title"]
        assert job["apply_url"]


# ─────────────────────────────────────────────────────────────
# Greenhouse
# ─────────────────────────────────────────────────────────────

@responses.activate
def test_greenhouse_parses_payload():
    payload = {
        "jobs": [
            {
                "id": 12345,
                "title": "Senior Backend Engineer",
                "location": {"name": "Bengaluru, India"},
                "content": "<p>Join our team.</p>",
                "absolute_url": "https://boards.greenhouse.io/testco/jobs/12345",
                "updated_at": "2026-08-05T10:00:00Z",
            }
        ]
    }
    responses.add(
        responses.GET,
        "https://boards-api.greenhouse.io/v1/boards/testco/jobs",
        json=payload,
        status=200,
    )

    from listings.greenhouse.fetcher import fetch_greenhouse_jobs
    jobs = fetch_greenhouse_jobs({"name": "TestCo", "board_token": "testco", "domain": "testco.com"})

    _assert_canonical_shape(jobs, "greenhouse")
    assert jobs[0]["source_job_id"] == "gh_12345"
    assert jobs[0]["company"] == "TestCo"
    assert jobs[0]["company_domain"] == "testco.com"
    assert isinstance(jobs[0]["posted_at"], datetime)


# ─────────────────────────────────────────────────────────────
# Lever
# ─────────────────────────────────────────────────────────────

@responses.activate
def test_lever_parses_payload():
    payload = [
        {
            "id": "abc-123",
            "text": "Software Engineer",
            "categories": {"location": "Remote", "workplaceType": "remote"},
            "descriptionPlain": "We are looking for a great engineer to join our team.",
            "lists": [{"content": "<ul><li>Python</li><li>Django</li></ul>"}],
            "hostedUrl": "https://jobs.lever.co/testco/abc-123",
        }
    ]
    responses.add(
        responses.GET,
        "https://api.lever.co/v0/postings/testco",
        json=payload,
        status=200,
    )

    from listings.lever.fetcher import fetch_lever_jobs
    jobs = fetch_lever_jobs({"name": "TestCo", "slug": "testco", "domain": "testco.com"})

    _assert_canonical_shape(jobs, "lever")
    assert jobs[0]["source_job_id"] == "lv_abc-123"
    assert jobs[0]["work_type"] == "Remote"  # mapped from workplaceType
    assert jobs[0]["posted_at"] is None  # Lever doesn't expose date
    assert "missing_posted_at" in jobs[0]["data_quality_flags"]


# ─────────────────────────────────────────────────────────────
# Ashby
# ─────────────────────────────────────────────────────────────

@responses.activate
def test_ashby_parses_payload():
    payload = {
        "jobs": [
            {
                "id": "job-999",
                "title": "Data Engineer",
                "location": "San Francisco",
                "descriptionHtml": "<p>Great team, great mission.</p>",
                "jobUrl": "https://jobs.ashbyhq.com/testco/job-999",
                "publishedAt": "2026-08-01T00:00:00Z",
            }
        ]
    }
    responses.add(
        responses.GET,
        "https://api.ashbyhq.com/posting-api/job-board/testco",
        json=payload,
        status=200,
    )

    from listings.ashby.fetcher import fetch_ashby_jobs
    jobs = fetch_ashby_jobs({"name": "TestCo", "slug": "testco", "domain": "testco.com"})

    _assert_canonical_shape(jobs, "ashby")
    assert jobs[0]["source_job_id"] == "ash_job-999"
    assert isinstance(jobs[0]["posted_at"], datetime)


# ─────────────────────────────────────────────────────────────
# RemoteOK
# ─────────────────────────────────────────────────────────────

@responses.activate
def test_remoteok_parses_payload_and_extracts_logo():
    """RemoteOK is the one source that hands us a direct logo URL — must be preserved."""
    payload = [
        {"legal": "This is metadata, no id field"},
        {
            "id": "rok-777",
            "position": "Full Stack Developer",
            "company": "RemoteCorp",
            "location": "Worldwide",
            "description": "Join us to build cool things.",
            "url": "https://remoteok.com/jobs/rok-777",
            "date": "2026-08-01T00:00:00+00:00",
            "company_logo": "https://remoteok.com/cdn/logos/remotecorp.png",
        },
    ]
    responses.add(responses.GET, "https://remoteok.com/api", json=payload, status=200)

    from listings.remoteok.fetcher import fetch_remoteok_jobs
    jobs = fetch_remoteok_jobs()

    _assert_canonical_shape(jobs, "remoteok")
    assert jobs[0]["source_job_id"] == "rok_rok-777"
    assert jobs[0]["company"] == "RemoteCorp"
    assert jobs[0]["logo_url"] == "https://remoteok.com/cdn/logos/remotecorp.png"


# ─────────────────────────────────────────────────────────────
# Adzuna
# ─────────────────────────────────────────────────────────────

@responses.activate
def test_adzuna_parses_payload(monkeypatch):
    # Adzuna requires app_id and app_key at module level — stub them
    import listings.adzuna.fetcher as adzuna_mod
    monkeypatch.setattr(adzuna_mod, "ADZUNA_APP_ID", "test_id")
    monkeypatch.setattr(adzuna_mod, "ADZUNA_APP_KEY", "test_key")

    payload = {
        "results": [
            {
                "id": "adz-111",
                "title": "Backend Engineer",
                "company": {"display_name": "TestCo"},
                "location": {"area": ["UK", "London"]},
                "description": "Great backend role.",
                "redirect_url": "https://adzuna.com/details/adz-111",
                "created": "2026-08-01T00:00:00Z",
            }
        ]
    }
    # Adzuna's URL includes country + page + auth params — use regex-like matching
    responses.add(
        responses.GET,
        "https://api.adzuna.com/v1/api/jobs/gb/search/1",
        json=payload,
        status=200,
    )
    # No results on page 2 → pagination stops
    responses.add(
        responses.GET,
        "https://api.adzuna.com/v1/api/jobs/gb/search/2",
        json={"results": []},
        status=200,
    )

    from listings.adzuna.fetcher import fetch_adzuna_jobs
    jobs = fetch_adzuna_jobs("gb", "backend engineer", max_pages=2)

    _assert_canonical_shape(jobs, "adzuna")
    assert jobs[0]["source_job_id"] == "adz_adz-111"


# ─────────────────────────────────────────────────────────────
# Himalayas
# ─────────────────────────────────────────────────────────────

@responses.activate
def test_himalayas_parses_payload():
    ts_now = int(datetime.now().timestamp())
    payload = {
        "jobs": [
            {
                "guid": "hml-500",
                "title": "Remote DevOps Engineer",
                "companyName": "RemoteInc",
                "locationRestrictions": ["Worldwide"],
                "description": "<p>Build automation.</p>",
                "applicationLink": "https://himalayas.app/jobs/hml-500",
                "pubDate": ts_now,
            }
        ],
        "totalCount": 1,
    }
    responses.add(
        responses.GET,
        "https://himalayas.app/jobs/api",
        json=payload,
        status=200,
    )

    from listings.himalayas.fetcher import fetch_himalayas_jobs
    jobs = fetch_himalayas_jobs()

    _assert_canonical_shape(jobs, "himalayas")
    assert jobs[0]["source_job_id"] == "hml_hml-500"
    assert isinstance(jobs[0]["posted_at"], datetime)


# ─────────────────────────────────────────────────────────────
# WeWorkRemotely (RSS)
# ─────────────────────────────────────────────────────────────

@responses.activate
def test_weworkremotely_parses_rss():
    rss_body = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>Awesome Company: Senior React Developer</title>
        <link>https://weworkremotely.com/remote-jobs/awesome-react-dev</link>
        <guid>https://weworkremotely.com/remote-jobs/awesome-react-dev</guid>
        <region>Worldwide</region>
        <pubDate>Fri, 05 Aug 2026 12:00:00 GMT</pubDate>
        <description>&lt;p&gt;Join our React team building great products.&lt;/p&gt;</description>
      </item>
    </channel></rss>"""
    responses.add(
        responses.GET,
        "https://weworkremotely.com/remote-jobs.rss",
        body=rss_body,
        status=200,
        content_type="application/xml",
    )

    from listings.scraping.weworkremotely.fetcher import fetch_wwr_jobs
    jobs = fetch_wwr_jobs()

    _assert_canonical_shape(jobs, "weworkremotely")
    assert jobs[0]["company"] == "Awesome Company"
    assert jobs[0]["title"] == "Senior React Developer"
    assert jobs[0]["work_type"] == "Remote"


# ─────────────────────────────────────────────────────────────
# HackerNews header parser (isolated — no HTTP mocking needed)
# ─────────────────────────────────────────────────────────────

def test_hackernews_header_parser_extracts_company_title_location():
    """HN 'Who is hiring' posts follow a `Company | Title | Location | Remote/Hybrid` header."""
    from listings.hackernews.fetcher import _parse_header
    text = "TestCo | Senior Backend Engineer | New York, NY | REMOTE\n\nBuild cool things."
    result = _parse_header(text)
    assert result["company"] == "TestCo"
    assert result["title"] == "Senior Backend Engineer"
    assert result["work_type"] == "Remote"


def test_hackernews_header_parser_extracts_domain_from_url():
    """When the company field embeds a URL, the domain gets extracted."""
    from listings.hackernews.fetcher import _parse_header
    text = "TestCo https://testco.com | Senior Backend Engineer | Remote"
    result = _parse_header(text)
    assert result["company"] == "TestCo"
    assert result["company_domain"] == "testco.com"
