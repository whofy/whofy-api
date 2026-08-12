"""
Shared pytest fixtures for whofy-api tests.

Every test that needs a DB, auth, or an API client should pull the fixtures
from here rather than building them inline.

Key design notes:
  - `get_async_db` is imported into fetch_api routers at module load time
    (`from db.mongo import get_async_db`), so monkeypatching `db.mongo`
    alone doesn't reach the routers. We patch at every known import site.
  - FastAPI `Depends(get_current_user)` captures the function reference at
    router-definition time, so monkeypatching the module attribute is
    ineffective for that path. We use `app.dependency_overrides` instead.
  - `mongomock` shares state across `MongoClient()` instances by default;
    we explicitly drop the `whofy` database after each test.
"""
import pytest
from bson import ObjectId
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient
from mongomock import MongoClient as MongoMockClient


# Modules that import get_async_db by name — must be patched at each site.
_ASYNC_DB_IMPORT_SITES = ["fetch_api.jobs", "fetch_api.saved_jobs"]
_SYNC_DB_IMPORT_SITES = []  # extend as needed for ingestion tests

TEST_USER_ID = "test_user_123"


# ─────────────────────────────────────────────────────────────
# Database fixtures — one fresh in-memory Mongo per test
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def mock_async_db(monkeypatch):
    """Fresh mongomock-motor DB, wired into every module that uses get_async_db."""
    client = AsyncMongoMockClient()
    db = client["whofy"]

    def _get_db():
        return db

    def _get_client():
        return client

    monkeypatch.setattr("db.mongo.get_async_client", _get_client)
    monkeypatch.setattr("db.mongo.get_async_db", _get_db)
    for mod_path in _ASYNC_DB_IMPORT_SITES:
        monkeypatch.setattr(f"{mod_path}.get_async_db", _get_db, raising=False)

    yield db
    # AsyncMongoMockClient() creates fresh state per instance — no explicit cleanup needed.


@pytest.fixture
def mock_sync_db(monkeypatch):
    """Fresh mongomock (sync) DB — used by ingestion/storage tests."""
    client = MongoMockClient()
    db = client["whofy"]

    monkeypatch.setattr("db.mongo.get_client", lambda: client)
    monkeypatch.setattr("db.mongo.get_db", lambda: db)
    # storage.py now imports `get_client` directly from db.mongo — patch the local binding too.
    monkeypatch.setattr("listings.shared.storage.get_client", lambda: client, raising=False)

    yield db

    for name in list(db.list_collection_names()):
        db.drop_collection(name)  # sync — safe here


# ─────────────────────────────────────────────────────────────
# FastAPI test client (with mocked auth via dependency_overrides)
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def client(mock_async_db):
    """TestClient with DB mocked, auth stubbed via dependency_overrides, limiter disabled."""
    from main import app
    from fetch_api.auth import get_current_user
    from fetch_api.limiter import limiter

    # Depends() captures function refs at router-definition time — use dependency_overrides
    app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID

    # Also stub the limiter's inline import of get_current_user
    import fetch_api.auth as auth_module
    original_gcu = auth_module.get_current_user
    auth_module.get_current_user = lambda request=None: TEST_USER_ID

    was_enabled = limiter.enabled
    limiter.enabled = False
    try:
        with TestClient(app) as c:
            yield c
    finally:
        limiter.enabled = was_enabled
        auth_module.get_current_user = original_gcu
        app.dependency_overrides.clear()


@pytest.fixture
def unauth_client(mock_async_db):
    """TestClient with NO auth override — for tests that verify 401 behavior."""
    from main import app
    from fetch_api.limiter import limiter

    was_enabled = limiter.enabled
    limiter.enabled = False
    try:
        with TestClient(app) as c:
            yield c
    finally:
        limiter.enabled = was_enabled


@pytest.fixture
def auth_headers():
    """Bearer header — content is irrelevant when the `client` fixture is active."""
    return {"Authorization": "Bearer test-token"}


# ─────────────────────────────────────────────────────────────
# External-service stubs
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def mock_groq_chat(monkeypatch):
    """Stub the chatbot Groq call so tests never touch the real API."""
    async def _fake_response(message, history):
        return f"Mock reply to: {message[:40]}"

    # get_chat_response is imported by name into chatbot.router — patch at that site
    monkeypatch.setattr("chatbot.router.get_chat_response", _fake_response)


@pytest.fixture
def rate_limited_client_fresh(mock_async_db, mock_groq_chat):
    """
    Same as `client` but with SlowAPI enabled and its in-process counter
    reset — for testing rate-limit enforcement in isolation.
    """
    from main import app
    from fetch_api.auth import get_current_user
    from fetch_api.limiter import limiter
    import fetch_api.auth as auth_module

    app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID

    # SlowAPI's key function calls get_current_user inline to derive per-user buckets
    original_gcu = auth_module.get_current_user
    auth_module.get_current_user = lambda request=None: TEST_USER_ID

    # Reset the in-process SlowAPI storage so this test starts with a clean bucket
    if hasattr(limiter, "_storage") and hasattr(limiter._storage, "storage"):
        limiter._storage.storage.clear()
    elif hasattr(limiter, "reset"):
        limiter.reset()

    try:
        with TestClient(app) as c:
            yield c
    finally:
        auth_module.get_current_user = original_gcu
        app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────
# Data-factory fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def make_job():
    """Returns a callable that builds a valid Job dict; override any field via kwargs."""
    def _make(**overrides):
        now = datetime.now(timezone.utc)
        base = {
            "_id": ObjectId(),
            "source": "greenhouse",
            "source_job_id": "gh_test_123",
            "title": "Senior Software Engineer",
            "company": "Test Co",
            "location": "Bengaluru, India",
            "apply_url": "https://example.com/apply",
            "fingerprint": "greenhousegh_test_123",
            "posted_at": now,
            "added_at": now,
            "last_seen_at": now,
            "description": "Great role for Python + React devs",
            "company_domain": "test.co",
            "required_skills": ["Python", "React"],
            "work_type": "Remote",
            "experience_level": "Senior",
            "lang_checked": True,
            "data_quality_flags": [],
        }
        base.update(overrides)
        return base
    return _make


@pytest.fixture
def seed_job(mock_async_db, make_job):
    """Returns an awaitable that inserts a fake job and returns the inserted doc."""
    async def _seed(**overrides):
        job = make_job(**overrides)
        await mock_async_db.jobs.insert_one(job)
        return job
    return _seed
