"""
Tests for is_tech_job() and filter_tech_jobs() in listings/shared/tech_filter.py.

Guards the classifier that decides which jobs get ingested. Non-tech
roles must be rejected; the blacklist must beat the whitelist so ambiguous
titles ("Nurse — Python developer") don't slip through.
"""

from listings.shared.tech_filter import is_tech_job, filter_tech_jobs


# ─────────────────────────────────────────────────────────────
# Whitelist — accepted titles
# ─────────────────────────────────────────────────────────────

def test_accepts_software_engineer_title():
    assert is_tech_job("Software Engineer") is True


def test_accepts_data_scientist_title():
    assert is_tech_job("Senior Data Scientist") is True


def test_accepts_frontend_developer_title():
    assert is_tech_job("Frontend Developer") is True


def test_accepts_devops_engineer_title():
    assert is_tech_job("DevOps Engineer") is True


def test_accepts_via_language_keyword():
    """Titles containing a language name (Python, React, Golang, etc.) are accepted."""
    assert is_tech_job("Python Developer") is True
    assert is_tech_job("React Native Specialist") is True


def test_accepts_when_description_head_matches():
    """A neutral title still passes if the first 500 chars of the description hit the whitelist."""
    assert is_tech_job("Team Lead", "We're hiring a backend developer to join our platform team") is True


# ─────────────────────────────────────────────────────────────
# Blacklist — rejected titles
# ─────────────────────────────────────────────────────────────

def test_rejects_registered_nurse_title():
    assert is_tech_job("Registered Nurse") is False


def test_rejects_chef_title():
    assert is_tech_job("Executive Chef") is False


def test_rejects_lawyer_title():
    assert is_tech_job("Attorney") is False


def test_rejects_accountant_title():
    assert is_tech_job("Senior Accountant") is False


# ─────────────────────────────────────────────────────────────
# Blacklist must beat whitelist (title-first priority)
# ─────────────────────────────────────────────────────────────

def test_blacklist_beats_whitelist_in_title():
    """
    Ambiguous title where BOTH lists match — blacklist must win, otherwise
    "Nurse Manager (Python reporting)" style hybrid postings sneak in.
    """
    assert is_tech_job("Registered Nurse Python Developer") is False


# ─────────────────────────────────────────────────────────────
# Bounds / edge cases
# ─────────────────────────────────────────────────────────────

def test_empty_title_and_description_returns_false():
    assert is_tech_job("", "") is False


def test_description_matching_only_scans_first_500_chars():
    """A tech keyword buried past char 500 should NOT trigger a match."""
    padding = "This is a customer service role. " * 20  # ~660 chars
    late_keyword = padding + "python developer"
    assert is_tech_job("Customer Service Rep", late_keyword) is False


# ─────────────────────────────────────────────────────────────
# Batch helper
# ─────────────────────────────────────────────────────────────

def test_filter_tech_jobs_keeps_only_tech_entries():
    jobs = [
        {"title": "Software Engineer", "description": ""},
        {"title": "Registered Nurse", "description": ""},
        {"title": "Data Scientist", "description": ""},
        {"title": "Cashier", "description": ""},
    ]
    result = filter_tech_jobs(jobs)
    assert len(result) == 2
    titles = {j["title"] for j in result}
    assert titles == {"Software Engineer", "Data Scientist"}
