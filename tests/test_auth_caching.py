"""Guards for per-request token-verification caching and the JWKS TTL.

An authenticated request calls get_current_user twice by design: SlowAPI's
key function needs the user id to pick a rate-limit bucket, and the endpoint
declares Depends(get_current_user). Both did full RSA signature verification
independently. The result is now memoized on request.state.

The memo must be per-request — a cache that outlived the request would mean
one verified token authenticating a later, unrelated caller.
"""
import time

import pytest

import fetch_api.auth as auth


class _FakeState:
    pass


class _FakeRequest:
    """Minimal stand-in for starlette Request: headers dict + .state."""

    def __init__(self, token="tok"):
        self.headers = {"Authorization": f"Bearer {token}"}
        self.state = _FakeState()


@pytest.fixture
def stub_verification(monkeypatch):
    """Count how many times the signature path actually runs."""
    calls = {"verify": 0}

    monkeypatch.setattr(auth, "_get_public_key", lambda token: "fake-key")

    def _decode(token, key, **kwargs):
        calls["verify"] += 1
        return {"sub": "user_abc"}

    monkeypatch.setattr(auth.jwt, "decode", _decode)
    return calls


# ─────────────────────────────────────────────────────────────
# Per-request memoization
# ─────────────────────────────────────────────────────────────

def test_second_call_on_same_request_does_not_reverify(stub_verification, monkeypatch):
    monkeypatch.setattr(auth.settings, "clerk_secret_key", "sk_test", raising=False)
    request = _FakeRequest()

    first = auth.get_current_user(request)
    second = auth.get_current_user(request)

    assert first == second == "user_abc"
    assert stub_verification["verify"] == 1, (
        "token was verified twice for one request — memoization is not working"
    )


def test_each_request_verifies_independently(stub_verification, monkeypatch):
    """The memo must NOT leak across requests."""
    monkeypatch.setattr(auth.settings, "clerk_secret_key", "sk_test", raising=False)

    auth.get_current_user(_FakeRequest())
    auth.get_current_user(_FakeRequest())

    assert stub_verification["verify"] == 2


def test_memo_is_read_from_request_state(stub_verification, monkeypatch):
    """A pre-populated state short-circuits verification entirely."""
    monkeypatch.setattr(auth.settings, "clerk_secret_key", "sk_test", raising=False)
    request = _FakeRequest()
    request.state.user_id = "already_known"

    assert auth.get_current_user(request) == "already_known"
    assert stub_verification["verify"] == 0


def test_missing_bearer_header_still_rejected(monkeypatch):
    """Memoization must not weaken the unauthenticated path."""
    from fastapi import HTTPException

    request = _FakeRequest()
    request.headers = {}

    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(request)
    assert exc.value.status_code == 401


# ─────────────────────────────────────────────────────────────
# JWKS cache TTL
# ─────────────────────────────────────────────────────────────

def test_jwks_cache_is_reused_within_ttl(monkeypatch):
    fetches = {"n": 0}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            fetches["n"] += 1
            return {"keys": [{"kid": "k1"}]}

    monkeypatch.setattr(auth.requests, "get", lambda *a, **k: _Resp())
    auth._JWKS_CACHE.clear()

    auth._fetch_jwks()
    auth._fetch_jwks()

    assert fetches["n"] == 1


def test_jwks_cache_refetches_after_ttl_expires(monkeypatch):
    fetches = {"n": 0}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            fetches["n"] += 1
            return {"keys": [{"kid": "k1"}]}

    monkeypatch.setattr(auth.requests, "get", lambda *a, **k: _Resp())
    auth._JWKS_CACHE.clear()

    auth._fetch_jwks()
    # Jump past the TTL rather than sleeping through it. `auth.time` IS the
    # stdlib time module, so the replacement must not call back into the
    # patched name — capture the real clock reading first.
    future = time.monotonic() + auth._JWKS_TTL_SECONDS + 1
    monkeypatch.setattr(auth.time, "monotonic", lambda: future)
    auth._fetch_jwks()

    assert fetches["n"] == 2
    auth._JWKS_CACHE.clear()
