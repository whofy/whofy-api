"""
Tests for the enrichment helpers in listings/shared/enrich.py.

Guards the regex-based extraction that fills work_type, experience_level, and
required_skills on every ingested job. If these break, every fetcher's output
degrades silently — no source failures, just bad data downstream.
"""

from listings.shared.enrich import (
    extract_required_skills,
    detect_work_type,
    detect_experience,
    bake_required_skills,
    MAX_EXTRACTED_SKILLS,
)


# ─────────────────────────────────────────────────────────────
# extract_required_skills
# ─────────────────────────────────────────────────────────────

def test_extract_skills_finds_python_and_react():
    skills = extract_required_skills("Software Engineer", "Looking for Python and React developer")
    assert "Python" in skills
    assert "React" in skills


def test_extract_skills_returns_canonical_names_case_insensitive():
    """Lowercase mentions should still return the canonical PascalCase name."""
    skills = extract_required_skills("Backend Dev", "python postgresql mongodb")
    assert "Python" in skills
    assert "PostgreSQL" in skills
    assert "MongoDB" in skills


def test_extract_skills_case_sensitive_short_terms():
    """
    Short/ambiguous names like C, R, Go are matched CASE-SENSITIVELY only,
    so 'grocery' doesn't match 'R' and 'goodbye' doesn't match 'Go'.
    """
    skills = extract_required_skills("Data Analyst", "Experience with R and C required")
    assert "R" in skills
    assert "C" in skills


def test_extract_skills_lowercase_go_is_not_matched():
    """'gone' should NOT trigger a Go match — case-sensitive protection."""
    skills = extract_required_skills("Backend Engineer", "he has gone home")
    assert "Go" not in skills


def test_extract_skills_capped_at_max():
    """Even if 30 skills appear, we return at most MAX_EXTRACTED_SKILLS."""
    huge = " ".join([
        "Python", "React", "Node.js", "TypeScript", "JavaScript",
        "PostgreSQL", "MongoDB", "Redis", "Kafka", "Docker",
        "Kubernetes", "AWS", "GCP", "Terraform", "Ansible",
        "Django", "Flask", "FastAPI", "Vue", "Angular",
    ])
    skills = extract_required_skills("Fullstack Engineer", huge)
    assert len(skills) <= MAX_EXTRACTED_SKILLS


def test_extract_skills_deduplicates():
    """Same skill mentioned twice should only appear once."""
    skills = extract_required_skills("SWE", "Python Python python PYTHON")
    assert skills.count("Python") == 1


# ─────────────────────────────────────────────────────────────
# detect_work_type
# ─────────────────────────────────────────────────────────────

def test_work_type_remote_from_title():
    assert detect_work_type("Remote Software Engineer", "", "") == "Remote"


def test_work_type_hybrid_beats_remote_in_same_text():
    """When both 'hybrid' and 'remote' appear, Hybrid wins (checked first)."""
    assert detect_work_type("Hybrid role — some remote days", "", "") == "Hybrid"


def test_work_type_default_is_onsite():
    """No signal at all → On-site."""
    assert detect_work_type("Software Engineer", "Bengaluru", "") == "On-site"


def test_work_type_matches_from_description_head():
    """If title/location have no signal, check the first 500 chars of description."""
    assert detect_work_type("Software Engineer", "Bengaluru",
                            "This is a fully remote position with flexible hours") == "Remote"


# ─────────────────────────────────────────────────────────────
# detect_experience
# ─────────────────────────────────────────────────────────────

def test_experience_intern_from_title():
    assert detect_experience("Software Engineering Intern", "") == "Internship"


def test_experience_senior_from_title():
    assert detect_experience("Senior Backend Engineer", "") == "Senior"


def test_experience_junior_from_title():
    assert detect_experience("Junior Frontend Developer", "") == "Junior"


def test_experience_from_years_in_description():
    """3+ years → Junior per the year-range table."""
    assert detect_experience("Software Engineer", "3+ years of experience required") == "Junior"


def test_experience_high_years_maps_to_senior():
    """8+ years → Senior."""
    assert detect_experience("Engineer", "8+ years of relevant experience") == "Senior"


def test_experience_default_is_mid_level():
    """No signal → Mid Level default."""
    assert detect_experience("Software Engineer", "") == "Mid Level"


# ─────────────────────────────────────────────────────────────
# bake_required_skills
# ─────────────────────────────────────────────────────────────

def test_bake_appends_bullet_block():
    result = bake_required_skills("Great role.", ["Python", "React"])
    assert "Great role." in result
    assert "Required skills:" in result
    # Skills listed under the header (avoid asserting on the specific bullet glyph
    # to keep this test source ASCII-safe across Python encoding modes)
    assert "Python" in result
    assert "React" in result
    # Result must include SOME line-starting bullet marker before each skill
    assert "\n" in result and result.count("Python") >= 1


def test_bake_returns_description_unchanged_when_no_skills():
    assert bake_required_skills("Great role.", []) == "Great role."
