"""
Tests for the logo-resolution logic in fetch_api.jobs.serialize_job.

Guards the single-source-of-truth logo pipeline established by A-lite:
  1. logo_url on the doc wins (RemoteOK direct URL)
  2. Else Google favicon of company_domain (source-provided real domain)
  3. Else null → frontend renders a colored-letter fallback
Regression guard against the earlier "Google favicon of guessed domain" bug
that caused globe icons on the results page.
"""

from bson import ObjectId

from fetch_api.jobs import serialize_job


def _base_doc(**overrides):
    doc = {
        "_id": ObjectId(),
        "title": "Backend Engineer",
        "company": "TestCo",
        "location": "Remote",
        "apply_url": "https://example.com/apply",
        "source": "test",
        "work_type": "Remote",
        "experience_level": "Senior",
        "required_skills": ["Python"],
    }
    doc.update(overrides)
    return doc


def test_direct_logo_url_wins_over_company_domain():
    """RemoteOK-style: doc carries a direct logo URL — use it, ignore company_domain."""
    doc = _base_doc(
        logo_url="https://remoteok.com/cdn/testco.png",
        company_domain="testco.com",
    )
    out = serialize_job(doc)
    assert out["logoUrl"] == "https://remoteok.com/cdn/testco.png"


def test_company_domain_produces_google_favicon_url():
    """Greenhouse/Ashby/Lever/Workday-style: use Google favicon of the real domain."""
    doc = _base_doc(company_domain="anthropic.com")
    out = serialize_job(doc)
    assert out["logoUrl"] == "https://www.google.com/s2/favicons?domain=anthropic.com&sz=128"


def test_no_logo_url_and_no_domain_returns_null():
    """Adzuna/WWR-style: no logo info at all → null → frontend shows colored letter."""
    doc = _base_doc()  # no logo_url, no company_domain
    out = serialize_job(doc)
    assert out["logoUrl"] is None


def test_no_guessing_from_company_name_alone():
    """
    Regression guard — the OLD code would guess `{companyslug}.com` from the
    company name and construct a Google favicon URL that resolved to a globe.
    A-lite must NOT do this. Company name alone is not enough.
    """
    doc = _base_doc(company="Trigent Software Private Limited")
    out = serialize_job(doc)
    assert out["logoUrl"] is None  # no guessing → colored letter downstream


def test_empty_company_domain_treated_as_missing():
    """Sources that set company_domain to '' should behave like unset."""
    doc = _base_doc(company_domain="")
    out = serialize_job(doc)
    assert out["logoUrl"] is None
