"""Tests for the weekly source canary."""
from unittest.mock import patch

import pytest

from pipeline import canary


def _mock_response(status_code=200, json_data=None):
    class _Resp:
        def __init__(self):
            self.status_code = status_code
            self._json = json_data

        def json(self):
            return self._json

    return _Resp()


def test_probe_greenhouse_passes_on_healthy_response():
    with patch("pipeline.canary.requests.get") as mock_get:
        mock_get.return_value = _mock_response(
            json_data={"jobs": [{"title": "Software Engineer"}, {"title": "PM"}]}
        )
        assert canary.probe_greenhouse() == 2


def test_probe_greenhouse_fails_on_empty_jobs():
    with patch("pipeline.canary.requests.get") as mock_get:
        mock_get.return_value = _mock_response(json_data={"jobs": []})
        with pytest.raises(canary.ProbeFailure, match="only 0 jobs"):
            canary.probe_greenhouse()


def test_probe_greenhouse_fails_on_missing_title_field():
    with patch("pipeline.canary.requests.get") as mock_get:
        mock_get.return_value = _mock_response(
            json_data={"jobs": [{"id": 1}]}  # no title
        )
        with pytest.raises(canary.ProbeFailure, match="schema drift"):
            canary.probe_greenhouse()


def test_probe_greenhouse_fails_on_http_error():
    with patch("pipeline.canary.requests.get") as mock_get:
        mock_get.return_value = _mock_response(status_code=500)
        with pytest.raises(canary.ProbeFailure, match="HTTP 500"):
            canary.probe_greenhouse()


def test_probe_remoteok_filters_header_and_counts_jobs():
    with patch("pipeline.canary.requests.get") as mock_get:
        mock_get.return_value = _mock_response(json_data=[
            {"legal": "notice"},  # header
            {"id": "1", "position": "Engineer"},
            {"id": "2", "position": "Designer"},
        ])
        assert canary.probe_remoteok() == 2


def test_probe_adzuna_fails_when_secrets_missing(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    with pytest.raises(canary.ProbeFailure, match="not set"):
        canary.probe_adzuna()


def test_main_returns_1_when_any_probe_fails():
    def _passing():
        return 5

    def _failing():
        raise canary.ProbeFailure("simulated")

    with patch.dict(canary.PROBES, {"good": _passing, "bad": _failing}, clear=True):
        # Retry runs the failing probe twice — no time.sleep between (patched below)
        with patch("pipeline.canary.time.sleep"):
            assert canary.main() == 1


def test_main_returns_0_when_all_probes_pass():
    def _passing():
        return 3

    with patch.dict(canary.PROBES, {"a": _passing, "b": _passing}, clear=True):
        assert canary.main() == 0
