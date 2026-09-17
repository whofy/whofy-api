import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient

from config.settings import settings

# Supabase issues JWTs signed either with asymmetric keys (RS256/ES256, served
# at the project's JWKS endpoint) or, on projects still using the legacy shared
# secret, with HS256. We verify the asymmetric case against the JWKS and fall
# back to the shared secret when a token is HS256.

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        jwks_url = settings.supabase_jwks_url
        if not jwks_url:
            raise HTTPException(status_code=500, detail="SUPABASE_URL not configured")
        # PyJWKClient caches keys and refetches on an unknown kid (key rotation).
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
    return _jwks_client


def _decode_token(token: str) -> dict:
    try:
        alg = jwt.get_unverified_header(token).get("alg", "")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    # Supabase tokens carry aud="authenticated"; the issuer is <url>/auth/v1.
    decode_kwargs = {
        "audience": "authenticated",
        "options": {"verify_aud": True},
    }
    if settings.supabase_issuer:
        decode_kwargs["issuer"] = settings.supabase_issuer

    try:
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise HTTPException(
                    status_code=500,
                    detail="Token is HS256 but SUPABASE_JWT_SECRET is not configured",
                )
            return jwt.decode(
                token, settings.supabase_jwt_secret, algorithms=["HS256"], **decode_kwargs
            )

        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token, signing_key.key, algorithms=["RS256", "ES256"], **decode_kwargs
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def get_current_user(request: Request) -> str:
    """Verify the bearer token and return the Supabase user id.

    Called twice per authenticated request by design: once by SlowAPI's key
    function (to pick a per-user rate-limit bucket) and once by Depends() on
    the endpoint. Signature verification is not free, so the result is
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
    payload = _decode_token(token)

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing user ID")

    request.state.user_id = user_id
    return user_id
