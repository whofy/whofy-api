"""
Tests for the ingestion runners in listings/run_api.py and listings/run_scrapper.py.

Guards Fix #6 (F-03) — source failure visibility:
  - run_source_concurrently returns a structured result dict (name/status/duration/error)
  - Successful fetchers → status="success", error=None
  - Raising fetchers → status="failed", error captured (not re-raised)
  - Duration always measured
  - mp_executor kwarg is forwarded only to fetchers that accept it
  - run_ingestion SKIPS cleanup when any source failed
  - run_ingestion exits with status 1 when any source failed
"""

import pytest


# ─────────────────────────────────────────────────────────────
# run_source_concurrently — the core F-03 contract
# ─────────────────────────────────────────────────────────────

def test_run_source_success_returns_success_dict():
    from listings.run_api import run_source_concurrently

    def fake_fetcher():
        return None

    result = run_source_concurrently("TestSource", fake_fetcher, is_heavy=False)

    assert result["name"] == "TestSource"
    assert result["status"] == "success"
    assert result["error"] is None
    assert isinstance(result["duration"], float)
    assert result["duration"] >= 0


def test_run_source_captures_exception_as_failed():
    """
    F-03 regression guard — a raising fetcher must NOT propagate the exception.
    It must be captured in the result dict so the runner can decide what to do.
    """
    from listings.run_api import run_source_concurrently

    def failing_fetcher():
        raise ConnectionError("simulated network failure")

    result = run_source_concurrently("BrokenSource", failing_fetcher, is_heavy=False)

    assert result["name"] == "BrokenSource"
    assert result["status"] == "failed"
    assert "simulated network failure" in result["error"]
    assert isinstance(result["duration"], float)


def test_run_source_measures_duration_nontrivial():
    import time
    from listings.run_api import run_source_concurrently

    def slow_fetcher():
        time.sleep(0.05)

    result = run_source_concurrently("SlowSource", slow_fetcher, is_heavy=False)
    assert result["duration"] >= 0.04


def test_run_source_passes_mp_executor_if_accepted():
    """Fetchers that accept mp_executor= must receive the shared pool."""
    from listings.run_api import run_source_concurrently

    seen_kwargs = {}

    def fetcher_with_mp(mp_executor=None):
        seen_kwargs["mp_executor"] = mp_executor

    sentinel = object()
    result = run_source_concurrently("MPSource", fetcher_with_mp, is_heavy=False, mp_executor=sentinel)

    assert result["status"] == "success"
    assert seen_kwargs["mp_executor"] is sentinel


def test_run_source_omits_mp_executor_if_not_accepted():
    """Fetchers with no mp_executor kwarg must be called cleanly (no TypeError)."""
    from listings.run_api import run_source_concurrently

    was_called = {"count": 0}

    def fetcher_without_mp():
        was_called["count"] += 1

    result = run_source_concurrently("PlainSource", fetcher_without_mp, is_heavy=False, mp_executor=object())

    assert result["status"] == "success"
    assert was_called["count"] == 1


# ─────────────────────────────────────────────────────────────
# run_ingestion — the failure-gating behavior
# ─────────────────────────────────────────────────────────────


class _FakeProcessPoolExecutor:
    """Drop-in replacement for ProcessPoolExecutor that avoids subprocess spawn."""
    def __init__(self, *args, **kwargs):
        pass
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        return False
    def map(self, fn, iterable, chunksize=1):
        return map(fn, iterable)


@pytest.fixture
def _stub_runner_dependencies(monkeypatch):
    """
    Stub every I/O-touching or subprocess-spawning dependency inside run_ingestion
    so we can drive it with fake sources and observe the failure-gating logic.
    """
    calls = {"ensure_indexes": 0, "cleanup_expired": 0, "cleanup_non_english": 0}

    monkeypatch.setattr("listings.run_api.ensure_indexes", lambda: calls.__setitem__("ensure_indexes", calls["ensure_indexes"] + 1))
    monkeypatch.setattr("listings.run_api.cleanup_expired_jobs", lambda: (calls.__setitem__("cleanup_expired", calls["cleanup_expired"] + 1), 0)[1])
    monkeypatch.setattr("listings.run_api.cleanup_non_english_jobs", lambda: (calls.__setitem__("cleanup_non_english", calls["cleanup_non_english"] + 1), 0)[1])
    monkeypatch.setattr("listings.run_api.get_collection_stats", lambda: {"total_jobs": 0, "per_source": {}})

    # Avoid real subprocess spawn (slow on Windows, picklability issues with lambdas)
    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", _FakeProcessPoolExecutor)

    return calls


def _install_fake_sources(monkeypatch, source_specs):
    """
    Swap the source `main` functions imported into listings.run_api so run_ingestion
    exercises our fakes instead of the real fetchers.
    source_specs: list of (module_attr_name, callable) pairs.
    """
    for attr_name, fn in source_specs:
        monkeypatch.setattr(f"listings.run_api.{attr_name}", fn)


def test_run_ingestion_all_success_runs_cleanup(_stub_runner_dependencies, monkeypatch):
    """When every source succeeds, cleanup MUST run and the process MUST NOT exit with error."""
    _install_fake_sources(monkeypatch, [
        ("greenhouse_main", lambda mp_executor=None: None),
        ("lever_main", lambda mp_executor=None: None),
        ("ashby_main", lambda mp_executor=None: None),
        ("remoteok_main", lambda mp_executor=None: None),
        ("adzuna_main", lambda mp_executor=None: None),
        ("himalayas_main", lambda mp_executor=None: None),
    ])

    from listings.run_api import run_ingestion
    run_ingestion()  # should NOT raise SystemExit

    assert _stub_runner_dependencies["ensure_indexes"] == 1
    assert _stub_runner_dependencies["cleanup_expired"] == 1
    assert _stub_runner_dependencies["cleanup_non_english"] == 1


def test_run_ingestion_still_cleans_up_when_one_source_fails(_stub_runner_dependencies, monkeypatch):
    """
    One flaky source must NOT switch off retention.

    Cleanup used to be skipped whenever any source failed. Deletion requires
    RETENTION_DAYS of consecutive staleness, so a single failed run can't
    delete anything — but skipping cleanup let the collection grow past the
    Atlas budget cleanup exists to protect.

    The run is still marked failed (exit 1) so CI goes red and watchers get
    an email.
    """
    def failing_fetcher(mp_executor=None):
        raise RuntimeError("Adzuna API down")

    _install_fake_sources(monkeypatch, [
        ("greenhouse_main", lambda mp_executor=None: None),
        ("lever_main", lambda mp_executor=None: None),
        ("ashby_main", lambda mp_executor=None: None),
        ("remoteok_main", lambda mp_executor=None: None),
        ("adzuna_main", failing_fetcher),
        ("himalayas_main", lambda mp_executor=None: None),
    ])

    from listings.run_api import run_ingestion
    with pytest.raises(SystemExit) as exc_info:
        run_ingestion()

    assert exc_info.value.code == 1
    assert _stub_runner_dependencies["ensure_indexes"] == 1
    assert _stub_runner_dependencies["cleanup_expired"] == 1
    assert _stub_runner_dependencies["cleanup_non_english"] == 1


def test_run_ingestion_skips_cleanup_when_every_source_fails(_stub_runner_dependencies, monkeypatch):
    """
    Total failure is different from a flaky source — it means no network or no
    DB. Skip cleanup rather than issue deletes against a broken environment.
    """
    def failing_fetcher(mp_executor=None):
        raise RuntimeError("no network")

    _install_fake_sources(monkeypatch, [
        ("greenhouse_main", failing_fetcher),
        ("lever_main", failing_fetcher),
        ("ashby_main", failing_fetcher),
        ("remoteok_main", failing_fetcher),
        ("adzuna_main", failing_fetcher),
        ("himalayas_main", failing_fetcher),
    ])

    from listings.run_api import run_ingestion
    with pytest.raises(SystemExit) as exc_info:
        run_ingestion()

    assert exc_info.value.code == 1
    assert _stub_runner_dependencies["cleanup_expired"] == 0
    assert _stub_runner_dependencies["cleanup_non_english"] == 0
