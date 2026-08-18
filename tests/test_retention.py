"""Guard tests for the single retention window.

These constants lived in five places and drifted to 30 (fetchers) / 28
(pipeline) / 14 (storage) / 28 (chatbot prompt). The drift was silent and
cost roughly half the nightly enrichment work — fetchers pulled 30 days,
the pipeline enriched everything under 28, and storage deleted everything
over 14.

If a future change re-declares a local cutoff instead of importing
RETENTION_DAYS, one of these fails.
"""
from datetime import datetime, timedelta, timezone

from listings.shared.retention import RETENTION_DAYS


def test_pipeline_uses_shared_retention_window():
    """The enrichment age gate must match what storage will keep."""
    from listings.shared import pipeline

    just_inside = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS - 1)
    just_outside = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS + 1)

    assert pipeline._is_too_old(just_inside) is False
    assert pipeline._is_too_old(just_outside) is True


def test_storage_uses_shared_retention_window():
    """save_jobs' age filter must match the same window."""
    from listings.shared import storage

    just_inside = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS - 1)
    just_outside = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS + 1)

    assert storage._is_too_old(just_inside) is False
    assert storage._is_too_old(just_outside) is True


def test_fetchers_do_not_declare_their_own_age_cutoff():
    """
    Himalayas / WWR / Workday each used to carry MAX_AGE_DAYS = 30. Fetching
    a wider window than storage keeps means paying to download, HTML-strip,
    regex, and langdetect jobs that get deleted seconds later.
    """
    from listings.himalayas import fetcher as himalayas
    from listings.scraping.weworkremotely import fetcher as wwr
    from listings.scraping.workday import fetcher as workday

    for mod in (himalayas, wwr, workday):
        assert not hasattr(mod, "MAX_AGE_DAYS"), (
            f"{mod.__name__} re-declares its own age cutoff — import "
            f"RETENTION_DAYS from listings.shared.retention instead"
        )
        assert mod.RETENTION_DAYS == RETENTION_DAYS


def test_chatbot_prompt_states_the_real_retention_window():
    """
    The prompt is user-facing product documentation. It claimed 28 days while
    the code deleted at 14.
    """
    from chatbot.chat_service import SYSTEM_PROMPT

    assert f"{RETENTION_DAYS} days are removed" in SYSTEM_PROMPT, (
        "chatbot system prompt no longer states the real retention window"
    )
