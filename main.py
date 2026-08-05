from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from fetch_api.limiter import limiter

from fetch_api.jobs import router as jobs_router
from fetch_api.saved_jobs import router as saved_jobs_router
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
app.include_router(resume_router)
app.include_router(chat_router)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

origins = settings.cors_origins.split(",")
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
