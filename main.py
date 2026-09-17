from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from config.settings import settings

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from fetch_api.limiter import limiter

from fetch_api.jobs import router as jobs_router
from fetch_api.saved_jobs import router as saved_jobs_router
from fetch_api.account import router as account_router
from parsing.resume import router as resume_router
from chatbot.router import router as chat_router
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    from db.mongo import get_async_client
    get_async_client().close()


app = FastAPI(title="Whofy API", lifespan=lifespan)
app.include_router(jobs_router)
app.include_router(saved_jobs_router)
app.include_router(account_router)
app.include_router(resume_router)
app.include_router(chat_router)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# Strip whitespace and drop empties: CORS_ORIGINS is a comma-separated env var,
# and a natural "a.com, b.com" would otherwise yield " b.com", which matches no
# browser Origin header and fails silently.
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/ready")
@limiter.limit("10/minute")
async def ready(request: Request):
    """Readiness probe: pings each critical dependency and reports which
    ones are reachable. Returns 200 when all dependencies are up, 503 when
    any check fails so uptime tooling and deployment platforms can react."""
    checks: dict[str, str] = {}

    try:
        from db.mongo import get_async_client
        await get_async_client().admin.command("ping")
        checks["mongodb"] = "ok"
    except Exception as e:
        checks["mongodb"] = f"fail: {type(e).__name__}: {e}"

    try:
        import httpx
        jwks_url = settings.supabase_jwks_url
        if not jwks_url:
            checks["supabase_auth"] = "fail: SUPABASE_URL not configured"
        else:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(jwks_url)
            checks["supabase_auth"] = "ok" if resp.status_code == 200 else f"fail: status {resp.status_code}"
    except Exception as e:
        checks["supabase_auth"] = f"fail: {type(e).__name__}: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    body = {"status": "ready" if all_ok else "not_ready", "checks": checks}
    return JSONResponse(status_code=200 if all_ok else 503, content=body)
