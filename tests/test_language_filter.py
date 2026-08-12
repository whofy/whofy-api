"""
Tests for the English-only language filter used by ingestion.

Two functions of the same name exist:
  - listings.shared.pipeline._is_non_english(title, desc) — called during batch
    enrichment; returns True if the text is detectably non-English.
  - listings.shared.storage._is_non_english(job) — called during save; short-
    circuits to False if the job already has `lang_checked=True`.
"""

from listings.shared.pipeline import _is_non_english as pipeline_is_non_english
from listings.shared.storage import _is_non_english as storage_is_non_english


# ─────────────────────────────────────────────────────────────
# pipeline._is_non_english (title, desc) → bool
# ─────────────────────────────────────────────────────────────

def test_pipeline_english_text_is_not_non_english():
    """A clearly English job description must NOT be flagged as non-English."""
    title = "Senior Software Engineer"
    desc = (
        "We are looking for an experienced backend engineer to join our platform "
        "team. You will design and implement scalable microservices using Python "
        "and PostgreSQL. Strong communication skills and a passion for clean code required."
    )
    assert pipeline_is_non_english(title, desc) is False


def test_pipeline_spanish_text_is_non_english():
    title = "Ingeniero de Software"
    desc = (
        "Buscamos un ingeniero de software con experiencia en desarrollo backend "
        "para unirse a nuestro equipo. Se requiere conocimiento sólido de Python "
        "y bases de datos relacionales, así como habilidades de comunicación."
    )
    assert pipeline_is_non_english(title, desc) is True


def test_pipeline_german_text_is_non_english():
    title = "Softwareentwickler"
    desc = (
        "Wir suchen einen erfahrenen Softwareentwickler zur Verstärkung unseres "
        "Teams. Sie arbeiten mit modernen Technologien und entwickeln skalierbare "
        "Lösungen für unsere Kunden im Bereich der Cloud-Infrastruktur."
    )
    assert pipeline_is_non_english(title, desc) is True


def test_pipeline_empty_text_returns_false():
    """No text at all → can't classify → don't reject."""
    assert pipeline_is_non_english("", "") is False


# ─────────────────────────────────────────────────────────────
# storage._is_non_english (job dict) — respects lang_checked flag
# ─────────────────────────────────────────────────────────────

def test_storage_skips_recheck_when_lang_checked_true():
    """
    A doc already marked lang_checked=True is trusted — no re-run of langdetect.
    This is the optimization that dropped cleanup from 4min → 0.07s (per SPEC.md).
    """
    job = {
        "title": "Ingeniero de Software",  # would be flagged non-English if checked
        "description": "Buscamos un ingeniero con experiencia.",
        "lang_checked": True,
    }
    assert storage_is_non_english(job) is False


def test_storage_runs_langdetect_when_lang_checked_missing():
    """
    Legacy docs (before the lang_checked flag existed) should still be
    checked and flagged if they turn out to be non-English.
    """
    job = {
        "title": "Softwareentwickler",
        "description": (
            "Wir suchen einen erfahrenen Softwareentwickler mit fundierten "
            "Kenntnissen in Python und modernen Cloud-Technologien."
        ),
        # no lang_checked key at all
    }
    assert storage_is_non_english(job) is True
