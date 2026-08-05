from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request, HTTPException

def get_user_or_ip(request: Request) -> str:
    """
    Returns the user ID if a valid JWT is present, fully verified via Clerk JWKS.
    Falls back to remote IP for public unauthenticated requests.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        # Import here to avoid circular imports during startup
        from fetch_api.auth import get_current_user
        try:
            user_id = get_current_user(request)
            return f"user:{user_id}"
        except HTTPException:
            # Reject invalid tokens immediately before they consume rate limit slots
            raise
    
    return get_remote_address(request)

# NOTE: The server currently runs with a single uvicorn worker.
# In-memory rate limiting will effectively multiply the real limit by the worker count.
# If we scale to multiple workers in production, we will need to switch this to a Redis backend.
limiter = Limiter(key_func=get_user_or_ip)
