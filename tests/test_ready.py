"""Tests for the /api/ready readiness probe."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def ready_client(mock_async_db, monkeypatch):
    """Client without auth overrides — /api/ready is public."""
    from main import app
    from fetch_api.limiter import limiter

    was_enabled = limiter.enabled
    limiter.enabled = False
    try:
        with TestClient(app) as c:
            yield c
    finally:
        limiter.enabled = was_enabled


def _patch_jwks(monkeypatch, result):
    """Replace _fetch_jwks with something that returns `result` or raises it."""
    def _fake():
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("fetch_api.auth._fetch_jwks", _fake)


def test_ready_returns_200_when_all_dependencies_ok(ready_client, monkeypatch):
    _patch_jwks(monkeypatch, {"keys": [{"kid": "abc"}]})

    resp = ready_client.get("/api/ready")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["mongodb"] == "ok"
    assert body["checks"]["clerk_jwks"] == "ok"


def test_ready_returns_503_when_jwks_fetch_fails(ready_client, monkeypatch):
    _patch_jwks(monkeypatch, RuntimeError("clerk unreachable"))

    resp = ready_client.get("/api/ready")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["mongodb"] == "ok"
    assert body["checks"]["clerk_jwks"].startswith("fail:")
    assert "clerk unreachable" in body["checks"]["clerk_jwks"]


def test_ready_returns_503_when_jwks_returns_empty_keys(ready_client, monkeypatch):
    _patch_jwks(monkeypatch, {"keys": []})

    resp = ready_client.get("/api/ready")

    assert resp.status_code == 503
    assert resp.json()["checks"]["clerk_jwks"] == "fail: empty keys list"


def test_ready_returns_503_when_mongo_ping_fails(ready_client, monkeypatch):
    _patch_jwks(monkeypatch, {"keys": [{"kid": "abc"}]})

    class _BrokenClient:
        class admin:
            @staticmethod
            async def command(*args, **kwargs):
                raise ConnectionError("mongo down")

        @staticmethod
        def close():
            pass

    monkeypatch.setattr("db.mongo.get_async_client", lambda: _BrokenClient)

    resp = ready_client.get("/api/ready")

    assert resp.status_code == 503
    body = resp.json()
    assert body["checks"]["mongodb"].startswith("fail:")
    assert "mongo down" in body["checks"]["mongodb"]


def test_ready_reports_both_failures_at_once(ready_client, monkeypatch):
    _patch_jwks(monkeypatch, RuntimeError("clerk down"))

    class _BrokenClient:
        class admin:
            @staticmethod
            async def command(*args, **kwargs):
                raise ConnectionError("mongo down")

        @staticmethod
        def close():
            pass

    monkeypatch.setattr("db.mongo.get_async_client", lambda: _BrokenClient)

    resp = ready_client.get("/api/ready")

    assert resp.status_code == 503
    checks = resp.json()["checks"]
    assert checks["mongodb"].startswith("fail:")
    assert checks["clerk_jwks"].startswith("fail:")
