"""
Tests for HTML → text normalization helpers in listings/shared/normalize.py.

Guards against regressions of the summarization + HTML-entity handling used
in every fetcher's description-cleaning pipeline.
"""

from listings.shared.normalize import (
    strip_html,
    full_text,
    first_paragraph,
    extract_bullets,
)


# ─────────────────────────────────────────────────────────────
# strip_html — summarizes to first paragraph + first bullets
# ─────────────────────────────────────────────────────────────

def test_strip_html_removes_tags():
    html = "<p>This is a great role for backend engineers with Python experience.</p>"
    result = strip_html(html)
    assert "<p>" not in result
    assert "great role" in result


def test_strip_html_decodes_nested_entities_fully():
    """Multi-pass entity decoding — &amp;amp;copy; must resolve all the way to ©."""
    html = "<p>Copyright &amp;amp;copy; 2026 Whofy. This is a long enough paragraph now.</p>"
    result = strip_html(html)
    # No entity remnants should survive
    assert "&amp;" not in result
    assert "&copy;" not in result
    # And the innermost text is preserved
    assert "Copyright" in result
    assert "2026 Whofy" in result


def test_strip_html_summarizes_intro_plus_bullets():
    """Keeps first meaningful paragraph and up to 5 bullets."""
    html = (
        "<p>This role is for a senior backend engineer with 5+ years of experience.</p>"
        "<ul>"
        "<li>Design scalable systems</li>"
        "<li>Write Python code</li>"
        "<li>Deploy on AWS</li>"
        "<li>Mentor junior devs</li>"
        "<li>Own SLO/SLI</li>"
        "<li>Bullet six should be dropped</li>"
        "<li>Bullet seven definitely dropped</li>"
        "</ul>"
    )
    result = strip_html(html)
    assert "senior backend engineer" in result
    assert "• Design scalable systems" in result
    assert "• Own SLO/SLI" in result
    assert "Bullet six" not in result
    assert "Bullet seven" not in result


def test_strip_html_empty_input_returns_empty():
    assert strip_html("") == ""
    assert strip_html(None) == ""


def test_strip_html_malformed_html_does_not_crash():
    """Broken markup should return SOME text without raising."""
    html = "<p>Unclosed paragraph <li> mixed with <div>random"
    result = strip_html(html)
    assert isinstance(result, str)


# ─────────────────────────────────────────────────────────────
# first_paragraph
# ─────────────────────────────────────────────────────────────

def test_first_paragraph_skips_short_lines():
    """Lines shorter than min_chars are skipped in favor of the first real paragraph."""
    text = "Short.\nAlso short.\nThis is a long enough paragraph to qualify as content."
    result = first_paragraph(text)
    assert "long enough paragraph" in result


# ─────────────────────────────────────────────────────────────
# extract_bullets
# ─────────────────────────────────────────────────────────────

def test_extract_bullets_caps_at_max_bullets():
    html = "<ul>" + "".join(f"<li>Item {i}</li>" for i in range(10)) + "</ul>"
    result = extract_bullets(html, max_bullets=5)
    assert len(result) == 5
    assert result[0] == "• Item 0"


def test_extract_bullets_returns_empty_for_no_html():
    assert extract_bullets("") == []


# ─────────────────────────────────────────────────────────────
# full_text — lossless (unlike strip_html which summarizes)
# ─────────────────────────────────────────────────────────────

def test_full_text_preserves_all_content():
    html = (
        "<p>Paragraph one.</p>"
        "<p>Paragraph two with more detail.</p>"
        "<ul><li>Bullet A</li><li>Bullet B</li></ul>"
    )
    result = full_text(html)
    assert "Paragraph one" in result
    assert "Paragraph two" in result
    assert "Bullet A" in result
    assert "Bullet B" in result
