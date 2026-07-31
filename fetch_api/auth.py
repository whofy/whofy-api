import jwt
import requests
from fastapi import Depends, HTTPException, Request
from functools import lru_cache

from config.settings import settings

_JWKS_CACHE = {}


def _get_clerk_jwks_url() -> str:
    key = settings.clerk_secret_key or ""
    # Extract the Clerk frontend API domain from the secret key isn't reliable,
    # so we use the Clerk JWKS endpoint via the Backend API instead.
    return "https://api.clerk.com/v1/jwks"


def _fetch_jwks() -> dict:
    if _JWKS_CACHE.get("keys"):
        return _JWKS_CACHE["keys"]

    resp = requests.get(
        _get_clerk_jwks_url(),
        headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
        timeout=10,
    )
    resp.raise_for_status()
    jwks = resp.json()
    _JWKS_CACHE["keys"] = jwks
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

    return user_id
