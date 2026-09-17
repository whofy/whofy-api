import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from config.settings import settings
from db.mongo import get_async_db
from fetch_api.auth import get_current_user
from fetch_api.limiter import limiter

router = APIRouter()


async def _delete_supabase_user(user_id: str) -> None:
    """Delete the auth user via the Supabase Admin API (service_role key)."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(
            status_code=500,
            detail="Account deletion is not configured (missing Supabase service role key)",
        )

    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users/{user_id}"
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "apikey": settings.supabase_service_role_key,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(url, headers=headers)

    # 200/204 = deleted; 404 = already gone, treat as success (idempotent).
    if resp.status_code not in (200, 204, 404):
        raise HTTPException(
            status_code=502,
            detail=f"Failed to delete auth user (Supabase returned {resp.status_code})",
        )


@router.delete("/api/account")
@limiter.limit("5/minute")
async def delete_account(request: Request, user_id: str = Depends(get_current_user)):
    """Permanently delete the current user: their saved jobs (MongoDB) and
    their Supabase auth account. Irreversible."""
    db = get_async_db()

    # Remove all per-user data we hold first, then the auth identity.
    await db.saved_jobs.delete_many({"user_id": user_id})
    await _delete_supabase_user(user_id)

    return {"status": "deleted"}
