import time

import jwt
import requests
from fastapi import HTTPException, Request

from config.settings import settings

_JWKS_CACHE = {}
# Clerk rotates signing keys periodically. The kid-miss path below already
# forces a refetch when we see an unknown key, but without a TTL a cache
# entry otherwise lives for the whole process lifetime.
_JWKS_TTL_SECONDS = 3600


def _get_clerk_jwks_url() -> str:
    # The Clerk frontend API domain can't be derived reliably from the secret
    # key, so we use the Backend API's JWKS endpoint instead. Keys returned
    # here are scoped to the instance the secret key belongs to.
    return "https://api.clerk.com/v1/jwks"


def _fetch_jwks() -> dict:
    cached = _JWKS_CACHE.get("keys")
    if cached and _JWKS_CACHE.get("expires_at", 0) > time.monotonic():
        return cached

    resp = requests.get(
        _get_clerk_jwks_url(),
        headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
        timeout=10,
    )
    resp.raise_for_status()
    jwks = resp.json()
    _JWKS_CACHE["keys"] = jwks
    _JWKS_CACHE["expires_at"] = time.monotonic() + _JWKS_TTL_SECONDS
    return jwks


def _get_public_key(token: str):
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="Token missing kid")

    jwks = _fetch_jwks()
    for key_data in jwks.get("keys", []):
        if key_data["kid"] == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(key_data)

    # Key not found — clear cache and retry once (key rotation)
    _JWKS_CACHE.clear()
    jwks = _fetch_jwks()
    for key_data in jwks.get("keys", []):
        if key_data["kid"] == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(key_data)

    raise HTTPException(status_code=401, detail="Token signing key not found")


def get_current_user(request: Request) -> str:
    """Verify the bearer token and return the Clerk user id.

    Called twice per authenticated request by design: once by SlowAPI's key
    function (to pick a per-user rate-limit bucket) and once by Depends() on
    the endpoint. RSA signature verification is not free, so the result is
    memoized on request.state — whichever caller runs first pays for it, the
    second gets it back for nothing. The cache lives and dies with the
    request, so a token is never trusted across requests.
    """
    cached = getattr(request.state, "user_id", None)
    if cached:
        return cached

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization token")

    token = auth_header[7:]

    if not settings.clerk_secret_key:
        raise HTTPException(status_code=500, detail="CLERK_SECRET_KEY not configured")

    try:
        public_key = _get_public_key(token)
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing user ID")

    request.state.user_id = user_id
    return user_id
