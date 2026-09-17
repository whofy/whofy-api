"""Guard for CORS origin parsing.

CORS_ORIGINS is a comma-separated env var. The natural way to write one —
"https://a.com, https://b.com" — used to produce " https://b.com" with a
leading space, which never matches a browser's Origin header. The failure is
silent: no error, no log, the second origin simply stops working.
"""


def _parse(raw: str) -> list[str]:
    """Mirror of the parsing in main.py."""
    return [o.strip() for o in raw.split(",") if o.strip()]


def test_spaces_after_commas_are_stripped():
    assert _parse("https://a.com, https://b.com") == ["https://a.com", "https://b.com"]


def test_empty_segments_are_dropped():
    assert _parse("https://a.com,,https://b.com,") == ["https://a.com", "https://b.com"]


def test_single_origin_unchanged():
    assert _parse("http://localhost:5173") == ["http://localhost:5173"]


def test_whitespace_only_value_yields_no_origins():
    assert _parse("   ") == []


def test_main_module_applies_the_same_parsing(monkeypatch):
    """The real app must strip too, not just this test's copy."""
    import main

    assert all(o == o.strip() for o in main.origins)
    assert "" not in main.origins
