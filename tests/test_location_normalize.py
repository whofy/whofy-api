"""
Tests for _normalize_location() in listings/shared/storage.py.

Guards the location canonicalization that runs during save_jobs — takes
raw "bengaluru, in" style strings and canonicalizes to "Bengaluru, India"
using COUNTRY_CODE_MAP + KNOWN_CITIES lookups.
"""

from listings.shared.storage import _normalize_location


# ─────────────────────────────────────────────────────────────
# Basic canonicalization
# ─────────────────────────────────────────────────────────────

def test_normalizes_city_country_code_pair():
    """Country code in second position should map to full country name."""
    result = _normalize_location("Bengaluru, IN")
    assert "India" in result


def test_normalizes_known_city_alone_infers_country():
    """A city known to KNOWN_CITIES should infer its country automatically."""
    result = _normalize_location("Mumbai")
    assert "India" in result


def test_normalizes_multiple_country_code_variants():
    """USA/US/United States all map to the same canonical name."""
    for raw in ["New York, USA", "San Francisco, US", "Seattle, United States"]:
        result = _normalize_location(raw)
        assert "United States" in result


# ─────────────────────────────────────────────────────────────
# Remote handling
# ─────────────────────────────────────────────────────────────

def test_normalizes_remote_keyword_to_remote():
    """Bare 'remote' → 'Remote'."""
    assert _normalize_location("remote") == "Remote"
    assert _normalize_location("Work from home") == "Remote"


# ─────────────────────────────────────────────────────────────
# Multi-location and edge cases
# ─────────────────────────────────────────────────────────────

def test_normalizes_semicolon_separated_multi_location():
    """Multiple locations joined by ; should be split and normalized independently."""
    result = _normalize_location("Bengaluru, IN; Mumbai, IN")
    assert "India" in result
    assert ";" in result  # multi-location preserved with separator


def test_empty_input_returns_empty():
    assert _normalize_location("") == ""
    assert _normalize_location("   ") == ""


def test_unknown_location_passes_through():
    """Unknown city/country should NOT crash — return something sensible."""
    result = _normalize_location("Atlantis")
    assert isinstance(result, str)
    assert len(result) > 0
