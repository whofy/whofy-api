# Whofy-API — Complete Codebase Audit (Updated)

> **Generated:** 2026-08-01 | All data below is from real file reads and command output, reflecting the current state after all Priority 0-3 fixes.

---

## 1. FOLDER-BY-FOLDER BREAKDOWN

### Complete File Tree (excluding `.venv/`, `.git/`, `__pycache__/`)

```
whofy-api/
├── .github/
│   └── workflows/
│       └── ingestion.yml            (32 lines)
├── chatbot/
│   ├── __init__.py                  (0 lines)
│   ├── chat_service.py              (103 lines)
│   └── router.py                    (20 lines)
├── config/
│   └── settings.py                  (20 lines)
├── db/
│   ├── __init__.py                  (0 lines)
│   └── mongo.py                     (32 lines)
├── fetch_api/
│   ├── __init__.py                  (0 lines)
│   ├── auth.py                      (82 lines)
│   ├── jobs.py                      (321 lines)
│   └── saved_jobs.py                (103 lines)
├── listings/
│   ├── __init__.py                  (0 lines)
│   ├── run_api.py                   (112 lines)
│   ├── run_scrapper.py              (108 lines)
│   ├── adzuna/
│   │   ├── __init__.py              (0 lines)
│   │   └── fetcher.py               (233 lines)
│   ├── ashby/
│   │   ├── __init__.py              (0 lines)
│   │   └── fetcher.py               (158 lines)
│   ├── greenhouse/
│   │   ├── __init__.py              (0 lines)
│   │   └── fetcher.py               (258 lines)
│   ├── hackernews/
│   │   ├── __init__.py              (0 lines)
│   │   └── fetcher.py               (193 lines)
│   ├── himalayas/
│   │   ├── __init__.py              (0 lines)
│   │   └── fetcher.py               (167 lines)
│   ├── lever/
│   │   ├── __init__.py              (0 lines)
│   │   └── fetcher.py               (117 lines)
│   ├── remoteok/
│   │   ├── __init__.py              (0 lines)
│   │   └── fetcher.py               (71 lines)
│   ├── scraping/
│   │   ├── __init__.py              (0 lines)
│   │   ├── linkedin/
│   │   │   └── fetcher.py           (303 lines)
│   │   ├── weworkremotely/
│   │   │   ├── __init__.py          (0 lines)
│   │   │   └── fetcher.py           (143 lines)
│   │   └── workday/
│   │       ├── __init__.py          (0 lines)
│   │       └── fetcher.py           (272 lines)
│   └── shared/
│       ├── __init__.py              (0 lines)
│       ├── enrich.py                (361 lines)
│       ├── logos.py                  (174 lines)
│       ├── normalize.py             (102 lines)
│       ├── storage.py               (400+ lines)
│       └── tech_filter.py           (78 lines)
├── parsing/
│   ├── __init__.py                  (0 lines)
│   ├── resume.py                    (55 lines)
│   └── resume_parser.py             (107 lines)
├── pipeline/
│   ├── __init__.py                  (0 lines)
│   ├── audit_indexes.py             (28 lines)
│   ├── backfill_enrichment.py       (40 lines)
│   ├── backfill_fingerprints.py     (55 lines)
│   ├── cleanup.py                   (19 lines)
│   └── fix_duplicate_skills.py      (51 lines)
├── tests/
│   └── fixtures/
│       └── .gitkeep                 (empty)
├── .env                             (9 lines — REAL SECRETS)
├── .env.example                     (6 lines)
├── .gitignore                       (6 lines)
├── generate_audit_outputs.py        (68 lines)
├── ingest_api.py                    (8 lines)
├── ingest_scrapper.py               (8 lines)
├── main.py                          (38 lines)
├── requirements.txt                 (17 lines)
├── AUDIT.md                         (docs)
└── SPEC.md                          (docs)
```

*(Note: Dead folders `matching/`, `sources/`, `models/`, and `node_modules/` have been removed.)*

---

### Per-Folder Details

---

#### `.github/workflows/`

##### `ingestion.yml` (32 lines)
Full contents now properly execute the ingestion using the active endpoints (`ingest_api.py` and `ingest_scrapper.py`) rather than the deleted `run_all.py`.

---

#### `chatbot/`
| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 0 | Empty package marker |
| `chat_service.py` | 103 | Groq LLM chatbot service (`llama-3.3-70b-versatile`); system prompt defines Whofy platform knowledge; handles rate limits |
| `router.py` | 20 | FastAPI router exposing `POST /api/chat` |

---

#### `config/`
| File | Lines | Purpose |
|------|-------|---------|
| `settings.py` | 20 | Pydantic `BaseSettings` class; loads `.env` via `pydantic-settings`; defines `mongodb_uri`, `cors_origins`, `groq_api_key`, `adzuna_app_id`, `adzuna_app_key`, `clerk_secret_key` |

*(Note: `sources.py` empty stub was removed).*

---

#### `db/`
| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 0 | Empty package marker |
| `mongo.py` | 32 | DB module providing both sync (`pymongo.MongoClient` via `get_client()`/`get_db()`) and async (`motor.AsyncIOMotorClient` via `get_async_client()`/`get_async_db()`) clients; both use `@lru_cache` for singleton |

---

#### `fetch_api/`
| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 0 | Empty package marker |
| `auth.py` | 82 | Clerk JWT auth — fetches JWKS from Clerk Backend API, verifies RS256 tokens, extracts `sub` as user ID; uses sync `requests.get` for JWKS fetch |
| `jobs.py` | 321 | Main API router: `GET /api/matches` (skill-based matching via `$text` + aggregation), `GET /api/search` (text search with token-level precision), `GET /api/locations`, `GET /api/companies`, `GET /api/sources`, `GET /api/jobs/{id}` |
| `saved_jobs.py` | 103 | Saved jobs CRUD: `POST /api/saved-jobs`, `DELETE /api/saved-jobs/{id}`, `GET /api/saved-jobs`, `GET /api/saved-jobs/ids`; all require Clerk auth |

---

#### `listings/` — 10 source fetchers + shared utilities

**API-based sources** (consumed by `run_api.py`):
- `adzuna/fetcher.py` (233 lines)
- `ashby/fetcher.py` (158 lines)
- `greenhouse/fetcher.py` (258 lines)
- `himalayas/fetcher.py` (167 lines)
- `lever/fetcher.py` (117 lines)
- `remoteok/fetcher.py` (71 lines)

**Scraping-based sources** (consumed by `run_scrapper.py`):
- `scraping/linkedin/fetcher.py` (303 lines)
- `scraping/weworkremotely/fetcher.py` (143 lines)
- `scraping/workday/fetcher.py` (272 lines)
- `hackernews/fetcher.py` (193 lines)

**Runner files:**
| File | Lines | Purpose |
|------|-------|---------|
| `run_api.py` | 112 | Runs all 6 API sources concurrently (`ThreadPoolExecutor`); includes fetcher timings |
| `run_scrapper.py` | 108 | Runs 4 scraping sources concurrently; includes fetcher timings |

**Shared utilities** (`listings/shared/`):
| File | Purpose |
|------|---------|
| `enrich.py` | Work type detection, experience level detection, skill extraction against 400+ skill vocabulary. |
| `logos.py` | Logo resolution via Clearbit API; caches results in `company_logos`. |
| `normalize.py` | HTML→text conversion using BeautifulSoup. |
| `storage.py` | **Core ingestion storage**: `save_jobs()` (upsert with fingerprint dedup, language filter with `lang_checked` flagging), `cleanup_expired_jobs()`, `cleanup_non_english_jobs()` (ProcessPoolExecutor + bulk updates), `ensure_indexes()`. |
| `tech_filter.py` | Tech/non-tech job classification via regex whitelist/blacklist. |

---

#### `parsing/`
| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 0 | Empty package marker |
| `resume.py` | 55 | FastAPI router for `POST /api/upload-resume`; handles file validation, delegates to `resume_parser.py` |
| `resume_parser.py` | 107 | Extracts text from PDF / DOCX; sends to Groq LLM for structured extraction |

---

#### `pipeline/`
| File | Purpose |
|------|---------|
| `audit_indexes.py` | One-off utility to list all MongoDB indexes |
| `backfill_enrichment.py` | Backfills `work_type`, `experience_level`, `required_skills` (Import typo fixed) |
| `backfill_fingerprints.py` | Recomputes fingerprint strings on all docs |
| `cleanup.py` | Manual cleanup runner |
| `fix_duplicate_skills.py` | One-time fix for duplicated "Required skills:" blocks (Import typo fixed) |

---

### Root-Level Files

| File | Purpose |
|------|---------|
| `.env.example` | Template for environment variables (Cleaned: removed unused keys, added GROQ and CLERK keys). |
| `.env` | **LIVE SECRETS** (real MongoDB URI, Groq key, Adzuna keys, Clerk key) |
| `.gitignore` | Ignores `.venv/`, `__pycache__/`, `node_modules/` |
| `ingest_api.py` / `ingest_scrapper.py` | Thin entry points for GitHub Actions / Local runs. |
| `main.py` | FastAPI app entry point; mounts 4 routers; CORS middleware; health check. |
| `requirements.txt` | Python dependencies (Cleaned: removed `python-jose`, `authlib`, `httpx`). |

---

## 2. THE FULL REQUEST FLOW

### A. User Request Flow (Frontend → API → MongoDB → Response)
*(Unchanged from previous audit — routes through `main.py` to `fetch_api/jobs.py`, leverages MongoDB text search and aggregation pipelines).*

### B. Ingestion Flow
```text
GitHub Action / Manual trigger: python ingest_api.py
│
▼
listings/run_api.py :: run_ingestion()
├── ensure_indexes() 
├── ThreadPoolExecutor(max_workers=6)
│   ├── Greenhouse, Lever, Ashby, RemoteOK, Adzuna, Himalayas
│   │   ├── Fetch raw jobs
│   │   ├── Normalize to common schema
│   │   ├── filter_tech_jobs()
│   │   └── save_jobs(jobs, source=...)  →  storage.py
│   │       ├── Dedup, age filter, logo attachment
│   │       ├── Sets "lang_checked": True for accepted english jobs
│   │       └── Upsert via bulk_write
│
├── cleanup_expired_jobs()
├── cleanup_non_english_jobs()  →  Only queries docs where "lang_checked" != True, uses ProcessPoolExecutor
└── get_collection_stats()
```

---

## 3. EXTERNAL DEPENDENCIES & API KEY INVENTORY

### Environment Variables Actually Used

| Variable | Defined in Settings | External Service |
|----------|:-------------------:|------------------|
| `MONGODB_URI` | ✅ `settings.mongodb_uri` | MongoDB Atlas (Free tier M0) |
| `GROQ_API_KEY` | ✅ `settings.groq_api_key` | Groq Cloud (LLM inference for Chat/Resumes) |
| `ADZUNA_APP_ID` | ✅ `settings.adzuna_app_id` | Adzuna job API |
| `ADZUNA_APP_KEY` | ✅ `settings.adzuna_app_key` | Adzuna job API |
| `CLERK_SECRET_KEY` | ✅ `settings.clerk_secret_key` | Clerk Auth API |
| `CORS_ORIGINS` | ✅ `settings.cors_origins` | Config |

*(Note: `.env.example` has been accurately updated to reflect exactly this list).*

---

## 4. DATABASE SCHEMA & STATE

### Collections
1. `jobs` — Main job listings (46,680+ docs)
2. `saved_jobs` — User-saved job bookmarks
3. `company_logos` — Cached logo URLs

### Indexes on `jobs`
1. Unique compound (dedup key): `("source", 1), ("source_job_id", 1)`
2. Sort by posted date: `("posted_at", -1), ("_id", 1)`
3. Expiry tracking: `("last_seen_at", -1)`
4. Cleanup/expiry: `("added_at", -1)`
5. Full-text search: `("title", "text"), ("description", "text")`
6. Filter by work type: `("work_type", 1)`
7. Filter by experience: `("experience_level", 1)`

---

## 5. DEPENDENCY AUDIT

Unused dependencies (`python-jose`, `authlib`, `httpx`) have been completely purged from `requirements.txt` and the virtual environment.

Active dependencies include: `fastapi`, `uvicorn`, `pymongo`, `motor`, `pydantic`, `pydantic-settings`, `python-dotenv`, `python-multipart`, `requests`, `PyJWT`, `pymupdf`, `python-docx`, `beautifulsoup4`, `groq`, `langdetect`.

---

## 6. CURRENT ARCHITECTURE WEAKNESSES (Remaining Scalability Concerns)

*Note: Critical weaknesses like broken CI/CD pipelines, broken cleanup bottlenecks, dead folders, missing `.gitignore` paths, and inaccurate `.env.example` configurations have all been **resolved**.*

### 1. Two Separate MongoClient Singletons
`db/mongo.py` provides `get_client()` (sync) and `get_async_client()` (async). But `storage.py` creates its **own** separate `MongoClient` singleton (`_client_instance`), never going through `db/mongo.py`. This means two separate connection pools to the same cluster.

### 2. Sync HTTP Call in Async API Path
`auth.py` uses **sync `requests.get()`** to fetch Clerk JWKS — this blocks the async event loop on every first request (and on key rotation).

### 3. Sync PyMongo in Ingestion vs Async Motor in API — No Shared Abstraction
- API endpoints use `motor` (async) via `db/mongo.py`
- Ingestion code uses `pymongo` (sync) via its own client in `storage.py`
- No shared repository pattern or data access layer

### 4. `listings/` Does Too Many Things
The `listings/` folder is simultaneously a job fetcher registry, a shared data processing library (`shared/`), a CLI runner framework, and a MongoDB access layer. Splitting into separate services would require extracting `shared/` into a standalone package.

### 5. `fetch_api/jobs.py` Imports From `listings/shared/`
The API layer imports `detect_experience`, `detect_work_type`, `extract_required_skills` from `listings/shared/enrich.py` and `strip_html` from `normalize.py`. This creates a hard dependency between the API server and the ingestion module hierarchy.

### 6. Company Lists Are Hardcoded
Every fetcher hardcodes its company list as Python constants (170 Greenhouse companies, 62 Ashby, 26 Workday, etc.). Adding/removing companies requires code changes and redeployment. 

### 7. Duplicate ThreadPrefixLogger Boilerplate
`run_api.py` and `run_scrapper.py` are **nearly identical** — both copy-paste the same `ThreadPrefixLogger` class, `_patched_submit` monkeypatch, `heavy_semaphore`, and `run_source_concurrently` function.

### 8. No Rate Limiting on Public API Endpoints
`/api/matches`, `/api/search`, `/api/locations`, `/api/companies`, `/api/sources` are all unauthenticated and have no rate limiting. Under load, `distinct()` queries on `/api/locations` and `/api/companies` would be expensive.

### 9. No Test Coverage
Zero test files exist. No unit tests, no integration tests, no API tests. Any refactoring is high-risk without test coverage as a safety net.
