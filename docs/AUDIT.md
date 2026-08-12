# Whofy-API — Full Codebase Audit

> **Generated:** 2026-08-10
> **Last updated:** 2026-08-11 (Phase 0 fixes applied — see §1a Fix Log)
> **Scope:** every tracked file under `D:\whofy\whofy-api\` (excluding `.git/`, `.venv/`, `__pycache__/`).
> **Method:** every file below was read end-to-end. Findings are grounded in the real code as it exists today, not inherited from prior audits. Where prior docs made claims that no longer match reality, this document overrides them.
> **Companion docs:** `SPEC.md` (history of past fixes), `CODE_REVIEW_ARCHITECTURE_AUDIT.md` (2026-08-08 deep review), `PARSING_AUDIT.md` (parser module — fully applied), `INGESTION_ARCHITECTURE.md` (intended pipeline contract), `AUDIT_DATA_POINTS.md` (schema reference), `groq_api_limits.md` (LLM quotas).

---

## 1. Executive Summary

Whofy-API is a modular FastAPI monolith (~4,500 lines of application code) fronting MongoDB Atlas, with a batch ingestion worker that scrapes ten sources into a single `jobs` collection. It works: `main.py` boots, `/api/health` returns OK, the ingestion GH Action runs daily, and the frontend is served correctly-shaped documents. The parsing module was fully hardened in the last pass (see `PARSING_AUDIT.md`).

**As of the 2026-08-11 fix pass, most of the P0/P1 blockers from the 2026-08-08 architecture review have been remediated** — see **§1a Session Fix Log** below. Data correctness, cost/abuse control, and ingestion observability moved from "high risk" to "good." What's left: JWT `iss`/`aud` validation (deferred pending Clerk dashboard values), cross-source dedup, a test suite, packaging, and the newly-logged company-logo-quality issue (N-17).

The audit originally surfaced additional issues that prior docs missed (hardcoded absolute paths from another developer's machine, a dead `matching/` directory that `SPEC.md` claims was deleted, a UTF-16 `.vscode/settings.json`, tracked `__pycache__`, a Workday adapter that stored `None` descriptions due to a duplicate dict key, and dead imports across every fetcher). The dict-key bug, the hardcoded paths, and the dead directory are now fixed.

**Health snapshot (updated 2026-08-11):**

| Area | Before Phase 0 | After Phase 0 | Notes |
|---|---|---|---|
| API surface | Working | **Working** | All routes respond; response shapes match what the UI expects |
| Data correctness | High risk | **Good** | Date bugs fixed (F-01/F-04/F-20); F-05 cross-source dedup still open (documented, non-destructive) |
| Auth (Clerk) | Incomplete | **Incomplete** | JWT `iss`/`aud` still unchecked — deferred pending Clerk dashboard values from user |
| Ingestion reliability | High risk | **Good** | Source failures now surface (`SourceRunResult` + `sys.exit(1)`); cleanup skipped on failure; GitHub email notification wired |
| Cost/abuse control | Weak | **Good** | Chatbot rate-limited, message/history capped, singleton Groq client. Resume upload already hardened. |
| Test coverage | None | **None** | Still nothing under `tests/` beyond `.gitkeep`. Phase 1 target. |
| Housekeeping | Poor | **Improved** | Hardcoded paths removed, dead `matching/` deleted. Root `__pycache__/` still tracked (user opt-out); `.vscode/settings.json` encoding still off. |
| Deployment reproducibility | Weak | **Weak** | Still no lockfile / Dockerfile / `pyproject.toml`. Phase 2 target. |
| **Company logo UX** | Not flagged | **⚠️ Open (N-17)** | Many companies show a generic globe icon on results page — backend returns Google favicon URL for guessed domains that Google doesn't recognize. Documented for Phase 2. |

**Top blockers before this is production-viable for real users** (status after 2026-08-11 fix pass):

1. ~~Fix expiry/date semantics~~ ✅ **DONE** (2026-08-11)
2. ~~Make source failures visible~~ ✅ **DONE** (2026-08-11)
3. Validate JWT `iss` + `aud`; move JWKS to an async client with TTL + refresh lock. ⏸ **DEFERRED** — needs Clerk dashboard values
4. ~~Add unique index on `saved_jobs(user_id, job_id)`; convert to upsert; validate `ObjectId` before use~~ ✅ **DONE** (2026-08-11)
5. ~~Rate-limit `/api/chat`, cap history length, singleton the Groq client~~ ✅ **DONE** (2026-08-11)
6. ~~Fix Workday's duplicate `description` key~~ ✅ **DONE** (2026-08-11)
7. Fix LinkedIn's datetime handling before it is ever re-enabled. ⬜ Still open (LinkedIn remains disabled — non-urgent)
8. ~~Purge the two hardcoded `c:\Users\chara\Desktop\...` paths~~ ✅ **DONE** (2026-08-11)

---

## 1a. Session Fix Log — 2026-08-11

An interactive fix pass was run through Phase 0. Six of seven blockers cleared; one deferred pending external inputs.

### ✅ Fixed and applied

| # | Fix | Files touched |
|---|---|---|
| 1 | **Workday `description` bug** — deleted duplicate `description: None` on line 238 that was silently overwriting the baked-skills string on line 235. Every Workday job saved from this point onward will carry a real description string instead of `None`. Also removed the now-inaccurate `missing_description` data-quality flag. Existing rows self-heal on next re-scrape (upsert). | `listings/scraping/workday/fetcher.py` |
| 2a | **Date Bug 1 (`_is_too_old`)** — function now accepts `datetime | str | None`. Previously called `.replace("Z", ...)` on any input, silently caught the resulting `TypeError`, and returned "not too old" — old jobs from Greenhouse/Ashby/Adzuna/RemoteOK/HackerNews (which pass datetimes) were slipping through the age filter. | `listings/shared/storage.py` |
| 2b | **Date Bug 2 (cleanup cutoff)** — `cleanup_expired_jobs` now passes a real `datetime` cutoff to MongoDB instead of a `.isoformat()` string. Prior string-vs-BSON-date comparison meant the query rarely matched → 0 deletions per run → DB accumulating stale docs. | `listings/shared/storage.py` |
| 2c | **Date Bug 3 (wrong timestamp)** — cleanup query switched from `added_at` to `last_seen_at`. Now: a job first ingested 40 days ago but still on the source today (fresh `last_seen_at`) is correctly retained. Previously such jobs were deleted and re-added the next day, causing flicker and unnecessary write churn. | `listings/shared/storage.py` |
| 4a | **Saved-jobs ObjectId validation (F-06)** — invalid job IDs on POST/DELETE now return clean `400 "Invalid job ID"` instead of `500`. Validation moved to top of each route in a `try/except InvalidId`, `oid` reused throughout. | `fetch_api/saved_jobs.py` |
| 4b | **Saved-jobs race-proof uniqueness (F-07)** — added unique compound index on `saved_jobs(user_id, job_id)` in `ensure_indexes()` + secondary `(user_id, saved_at desc)` for the list endpoint. Rewrote `save_job` to use atomic `update_one` with `$setOnInsert + upsert=True` — no more check-then-insert race. Removed the leaky `500 "Validation error: {e}"` handler that exposed Pydantic internals. | `fetch_api/saved_jobs.py`, `listings/shared/storage.py` |
| 4c | **Saved-jobs pagination + type fix (F-08)** — `GET /api/saved-jobs` now takes `?skip=&limit=` (defaults 0/50, bounded 200), returns `{jobs, total, skip, limit}` envelope matching `/api/matches`. Expired-branch `id` field wrapped in `str()` so it's a string, not a raw ObjectId. Removed dead `try/except InvalidId` and unused `valid_saved_docs` list. | `fetch_api/saved_jobs.py` |
| 4d | **PyObjectId serializer bug (new — N-18)** — root cause of "unsave broken" symptom. The `PlainSerializer(lambda x: str(x))` on `PyObjectId` in `models/job.py` was running during `model_dump()`, meaning `SavedJob.model_dump(by_alias=True)` converted `job_id` from `ObjectId` → **string** before insert. All saved-jobs docs had `job_id` stored as strings, making the DELETE query (which used `ObjectId`) never match → 404 on every unsave. Added `when_used='json'` so serialization only happens on JSON output, not on Python `dict` output for Mongo. Wiped 2 legacy string-typed records to clean the collection. | `models/job.py`, DB migration |
| 4e | **UI wire-up for pagination envelope** — updated `getSavedJobs(token, {skip, limit})` and `SavedJobs.jsx` to unwrap `data.jobs` + display `data.total` in the "N saved" header. | `whofy-ui/src/api/jobs.js`, `whofy-ui/src/pages/SavedJobs/SavedJobs.jsx` |
| 5a | **Chatbot rate limit (F-09 part 1)** — added `@limiter.limit("20/minute")` decorator on `POST /api/chat` + required `request: Request` param. Bots and abusers now hit the wall at request #21 in any 60-second window; real users unaffected. | `chatbot/router.py` |
| 5b | **Chatbot message + history caps (F-09 part 2)** — added `Field(min_length=1, max_length=3000)` on `message`, `Field(default_factory=list, max_length=30)` on `history`. Oversized requests rejected with 422 before touching Groq. Protects daily 200K-token Groq quota from single-request blowouts. | `chatbot/router.py` |
| 5c | **Chatbot singleton Groq client (N-09)** — extracted `_get_groq_client()` helper matching the pattern already used in `parsing/resume_parser.py:111`. Client now reused across requests instead of created per-request; ~200ms handshake saved per chat. Sanitized the on-missing-key error message. | `chatbot/chat_service.py` |
| 6 | **Ingestion failure visibility (F-03)** — `run_source_concurrently` in both runners now returns a `{name, status, duration, error}` result dict. `run_ingestion` collects results, prints a `--- Source results ---` summary with `[OK  ]` / `[FAIL]` markers, **skips cleanup entirely if any source failed** (data-safety), and calls `sys.exit(1)` on failure so GitHub Actions marks the run red → email notification fires. | `listings/run_api.py`, `listings/run_scrapper.py` |
| 7a | **Deleted dead `matching/` directory (N-02)** — contained only a stale `.pyc` from July 2025. Referenced nowhere. Prior audits claimed it was deleted; it wasn't. Now really deleted. | `matching/` removed |
| 7b | **Purged hardcoded absolute paths (N-01)** — removed `sys.path.insert(0, r"c:\Users\chara\Desktop\whofy\whofy-api")` from two pipeline scripts. Leftover from another developer's machine; misleading on any other host. | `pipeline/audit_indexes.py`, `pipeline/backfill_fingerprints.py` |

### ⏸ Deferred (waiting on external input)

| # | Fix | Blocker |
|---|---|---|
| 3 | JWT `iss` / `aud` validation (F-02) + async JWKS (F-17) | Needs the exact `iss` and `aud` strings from the Clerk dashboard (or decoded from any real JWT via jwt.io). ~5-minute fix once values are known. |

### ⏭️ Explicitly skipped by user

| # | Item | Reason |
|---|---|---|
| 7c | Untrack root `__pycache__/main.cpython-312.pyc` from git | User asked to leave all `__pycache__` and `__init__.py` alone. |

### 📝 Post-fix verification

- `python ingest_api.py` ran end-to-end in 482.7 seconds. All 6 sources returned `[OK]`. Cleanup ran, deleted 0 jobs (verified via `count_documents` — all jobs have `last_seen_at` within 28 days, i.e., cleanup is working correctly, there just isn't stale data yet). Diagnostic confirmed all 43,385 jobs have `last_seen_at` stored as datetime — no lurking string/date-type mismatch.
- UI rebuilt from Vite dev server, `/saved-jobs` page renders cleanly with new envelope shape; save/unsave verified working on fresh saves.

---

## 2. What Actually Exists — File Tree

```
whofy-api/
├── .env                                (secrets — gitignored)
├── .env.example
├── .github/workflows/ingestion.yml
├── .gitignore
├── .vscode/settings.json               (UTF-16 encoded — quirky)
├── __pycache__/                        ← tracked by mistake (not in .gitignore properly)
├── chatbot/
│   ├── __init__.py
│   ├── chat_service.py                 (102 lines)
│   └── router.py                       (19 lines)
├── config/
│   └── settings.py                     (20 lines)
├── db/
│   ├── __init__.py
│   └── mongo.py                        (31 lines)
├── docs/
│   ├── AUDIT.md                        ← this file
│   ├── AUDIT_DATA_POINTS.md
│   ├── CODE_REVIEW_ARCHITECTURE_AUDIT.md
│   ├── INGESTION_ARCHITECTURE.md
│   ├── PARSING_AUDIT.md
│   ├── SPEC.md
│   └── groq_api_limits.md
├── fetch_api/
│   ├── __init__.py
│   ├── auth.py                         (81 lines)
│   ├── jobs.py                         (322 lines)
│   ├── limiter.py                      (26 lines)
│   └── saved_jobs.py                   (119 lines)
├── generate_audit_outputs.py           (67 lines — Windows-only diagnostic)
├── ingest_api.py                       (7 lines)
├── ingest_scrapper.py                  (7 lines)
├── listings/
│   ├── __init__.py
│   ├── run_api.py                      (129 lines)
│   ├── run_scrapper.py                 (113 lines)
│   ├── adzuna/
│   │   ├── __init__.py
│   │   ├── fetcher.py                  (241 lines)
│   │   └── fetcher_test.py             (193 lines — NOT a test)
│   ├── ashby/                          (fetcher.py, 167 lines)
│   ├── greenhouse/                     (fetcher.py, 273 lines)
│   ├── hackernews/                     (fetcher.py, 203 lines)
│   ├── himalayas/                      (fetcher.py, 173 lines)
│   ├── lever/                          (fetcher.py, 129 lines)
│   ├── remoteok/                       (fetcher.py, 80 lines)
│   ├── scraping/
│   │   ├── __init__.py
│   │   ├── linkedin/fetcher.py         (302 lines — DISABLED in runner)
│   │   ├── weworkremotely/fetcher.py   (142 lines)
│   │   └── workday/fetcher.py          (275 lines)
│   └── shared/
│       ├── __init__.py
│       ├── enrich.py                   (380 lines — skill vocab + regex)
│       ├── logos.py                    (181 lines)
│       ├── normalize.py                (101 lines)
│       ├── pipeline.py                 (105 lines)
│       ├── storage.py                  (480 lines)
│       └── tech_filter.py              (77 lines)
├── main.py                             (44 lines)
├── matching/                           ← DEAD (only a stale `.pyc` inside)
│   └── __pycache__/ranker.cpython-312.pyc
├── models/
│   └── job.py                          (110 lines)
├── parsing/
│   ├── __init__.py
│   ├── resume.py                       (68 lines)
│   └── resume_parser.py                (180 lines)
├── pipeline/
│   ├── __init__.py
│   ├── audit_indexes.py                (27 lines — hardcoded absolute path)
│   ├── backfill_enrichment.py          (39 lines)
│   ├── backfill_fingerprints.py        (54 lines — hardcoded absolute path)
│   ├── cleanup.py                      (18 lines)
│   └── fix_duplicate_skills.py         (50 lines)
├── requirements.txt                    (15 deps)
├── test_rate_limit.py                  (22 lines — smoke script)
├── test_rate_limit_auth.py             (60 lines — smoke script)
└── tests/
    └── fixtures/.gitkeep               ← the entire test suite
```

Totals: ~4,500 lines Python across ~40 source files.

---

## 3. Architecture As Implemented

```
                       ┌────────────────────────────┐
                       │  FastAPI process (main.py) │
                       └─────────────┬──────────────┘
                                     │
        ┌────────────────────────────┼─────────────────────────────┐
        │                            │                             │
  fetch_api/jobs.py           fetch_api/saved_jobs.py       chatbot/router.py
  (matches, search,           (auth-gated CRUD)             parsing/resume.py
   locations, companies,             │
   sources, jobs/:id)                │
        │                            │
        ├──►  Motor async client (db/mongo.py, singleton via lru_cache)
        │
        ├──►  extract_required_skills / detect_work_type / detect_experience
        │     imported from listings/shared/enrich.py but NEVER CALLED here
        │     (dead import — line 10 of fetch_api/jobs.py)
        │
        └──►  strip_html imported from listings/shared/normalize.py (used)

                                                     ┌─── Groq (chat)
              fetch_api/auth.py → Clerk JWKS (sync `requests`, blocking)
                                                     └─── Groq (resume parse)

  GitHub Actions daily @ 00:00 UTC (ingestion.yml)
        │
        ├──► ingest_api.py     → listings/run_api.py     → 6 fetchers × ThreadPoolExecutor
        │                                                  + shared ProcessPoolExecutor for enrichment
        └──► ingest_scrapper.py→ listings/run_scrapper.py → 3 fetchers (LinkedIn disabled)
                                                            no shared MP pool — enrichment inline in-thread
                        │
                        └──► listings/shared/storage.py → SEPARATE sync PyMongo client
                                                          (bypasses db/mongo.py)
                                                          save_jobs / cleanup_* / ensure_indexes
```

**Key architectural facts (some good, some bad):**

- The FastAPI process uses **async Motor**; ingestion uses **sync PyMongo via its own singleton** (`storage.py:24 _client_instance`). Two connection pools to the same Atlas cluster.
- `main.py`'s lifespan only closes the async client on shutdown; the sync singleton in `storage.py` and the module-level `_groq_client` in `parsing/resume_parser.py` are never closed.
- `fetch_api/jobs.py` imports enrichment helpers from `listings/shared/enrich` — a hard coupling from API to ingestion internals. And the imports of `detect_experience`, `detect_work_type`, `extract_required_skills` on line 10 are **never used** (verified via grep). Only `strip_html` from `normalize` is actually used.
- Only 6 out of 10 fetchers go through the documented `process_jobs_batch` pipeline. LinkedIn / WWR / Workday / HN do their own enrichment inline — this contradicts `INGESTION_ARCHITECTURE.md`.
- `run_api.py` and `run_scrapper.py` are nearly identical: same monkey-patch of `ThreadPoolExecutor.submit`, same `ThreadPrefixLogger`, same `heavy_semaphore`, same `run_source_concurrently` — pure copy-paste.

---

## 4. File-By-File Findings

Legend for the **Verdict** column:
- **Keep** — working as intended, minor or no changes needed.
- **Update** — behavior is broken/incomplete/insecure but the file's role is right.
- **Refactor** — the code works but its shape is wrong; needs to move or be split.
- **Delete** — dead, obsolete, or should never have been committed.

### 4.1 Application bootstrap

#### `main.py` — **Update**
**Does:** FastAPI factory, mounts 4 routers, adds SlowAPI limiter + handler, adds CORS, `/api/health` liveness endpoint. Lifespan closes the async Mongo client on shutdown.
- ✅ Compact, readable, no bloat.
- ⚠️ **Lifespan only closes the async client** — sync `_client_instance` in `storage.py` and the singleton `_groq_client` in `resume_parser.py` leak on shutdown (irrelevant in prod since the process just dies, but nonstandard).
- ⚠️ `/api/health` is liveness-only. Add `/api/ready` that pings MongoDB and confirms JWKS is loaded.
- ⚠️ `cors_origins` is comma-split at request time without trimming whitespace — a stray space in `.env` produces a silently-non-matching origin.
- ⚠️ No app factory pattern → hard to spin up for tests.

#### `config/settings.py` — **Keep** (small update)
**Does:** Pydantic `BaseSettings`, absolute path to `.env`, loads 7 env vars. Explicit `PROJECT_ROOT` computation is a nice touch (works from any CWD).
- ⚠️ Every field is `Optional` — the app boots even without `MONGODB_URI`, then fails at the first DB call. A production-mode validator that requires the load-bearing keys would fail fast.

#### `db/mongo.py` — **Update**
**Does:** `@lru_cache`-wrapped sync + async Mongo clients, both with `certifi.where()` TLS bundle.
- ⚠️ **`storage.py` bypasses this entirely** with its own `_client_instance` global. Two singletons, two pools, two lifecycle owners.
- ⚠️ No `serverSelectionTimeoutMS`, no `connectTimeoutMS`, no maxPoolSize. Whatever pymongo/motor defaults are, they aren't documented.
- ⚠️ Motor is imported lazily inside `get_async_client()` — fine, but the sync import is at module top.

#### `models/job.py` — **Keep** (minor update)
**Does:** Pydantic v2 models for `Job`, `SavedJob`, `SavedJobSnapshot`, `CompanyLogo`. Custom `PyObjectId` annotation with proper `BeforeValidator`/`PlainSerializer`. Field validators to coerce empty-string → `None`.
- ✅ Well-typed. Datetimes are native (not strings). `data_quality_flags` uses an Enum. Required-vs-optional split matches ingestion reality.
- ⚠️ No length caps on `title`, `description`, `required_skills` — a runaway ingestion payload could store a 10MB description.
- ⚠️ These are simultaneously persistence models AND API response shapes. Split into `domain/` and `api/dto/` layers when refactoring.
- 📝 Note: prior `AUDIT.md` and `SPEC.md` both claim `models/` was deleted. It exists and is actively imported (`storage.py`, `saved_jobs.py`, `logos.py`).

### 4.2 API layer (`fetch_api/`)

#### `fetch_api/jobs.py` (322 lines) — **Update**
**Does:** All public read endpoints — `/api/matches` (skill-scored aggregation over `$text`), `/api/search` (token-precise text search with fallback), `/api/locations`, `/api/companies`, `/api/sources`, `/api/jobs/{id}`. Also owns `serialize_job()` used by `saved_jobs.py`.
- ✅ Search aggregation is genuinely clever: computes `title_hits` + `total_hits` via `$indexOfCP`, requires at least N-1 tokens to hit, falls back to plain textScore if strict match yields nothing.
- ✅ Location filter escapes the regex (no injection).
- ✅ `_JUNK_LOC_RE` heuristic keeps garbage out of the `/api/locations` dropdown.
- ⚠️ **Dead imports** (line 10): `detect_experience`, `detect_work_type`, `extract_required_skills` are never used in this file. Only `strip_html` from `normalize` is used.
- ⚠️ **Query cost:** `distinct()` on ~46,000 docs for every `/api/locations`, `/api/companies`, `/api/sources` call — no cache. Under public load this is a wall.
- ⚠️ **Big pages:** `limit=1000` allowed on `/api/matches` and `/api/search`. Combined with aggregation over description text, this can pin a Mongo core.
- ⚠️ **`_clean_description` runs on every response** — should be baked at ingestion time and stored clean.
- ⚠️ Public endpoints have rate limits (`30/minute`, `10/minute`), but SlowAPI is in-process (see `limiter.py`). Not shared across replicas.
- ⚠️ API layer importing from `listings/shared` = wrong boundary. Move `strip_html` up to a common `text/` module.

#### `fetch_api/saved_jobs.py` (119 lines) — **Update**
**Does:** `POST/DELETE/GET /api/saved-jobs`, `GET /api/saved-jobs/ids`. All auth-gated via Clerk.
- ⚠️ **`ObjectId(req.job_id)` on line 26 runs OUTSIDE the try** in `save_job` — a malformed ID becomes a 500 instead of 400. `unsave_job` (line 65) has the same pattern.
- ⚠️ **No unique index on `(user_id, job_id)`** — the check-then-insert on lines 26–48 races under concurrency and allows duplicate saves. Existing indexes list confirms only `_id`.
- ⚠️ Bare `except Exception` on line 56 hides schema/DB errors as generic 500 with raw exception string in the detail — that message leaks pydantic internals to the client.
- ⚠️ `GET /api/saved-jobs` caps at `length=1000` with no `skip`, no cursor. Silent truncation.
- ⚠️ Expired-snapshot branch (line 102) returns `"id": saved["job_id"]` — that's a raw `ObjectId`, not a string, unlike the normal `serialize_job` path.
- ⚠️ `saved_at` update time uses `datetime.now(timezone.utc)` at write and `.isoformat()` at read — good, consistent.

#### `fetch_api/auth.py` (81 lines) — **Update**
**Does:** Clerk JWT verification. Fetches JWKS from `api.clerk.com/v1/jwks` with the secret key, caches keys, retries once on `kid` miss (key rotation).
- ⚠️ **No `iss` validation, no `aud` validation** (`options={"verify_aud": False}` on line 70). A valid RS256 token from any Clerk instance that shares a key rotation window is accepted. This is P0.
- ⚠️ **Sync `requests.get()` inside async request path** — first request after startup and every key rotation blocks the event loop for up to 10 seconds.
- ⚠️ `_JWKS_CACHE` is a plain dict with no TTL, no refresh lock — a `kid` miss under concurrent load triggers a stampede of refresh calls.
- ⚠️ Variable naming: `_JWKS_CACHE["keys"] = jwks` stores the full JWKS object (with its own `.keys` list), then line 40 iterates `jwks.get("keys", [])`. Works but confusing.

#### `fetch_api/limiter.py` (26 lines) — **Update**
**Does:** SlowAPI `Limiter` with a `get_user_or_ip` key function that verifies the Clerk JWT first and only rate-limits by IP for unauthenticated requests.
- ⚠️ **Verifies the token twice** — once here in `get_user_or_ip`, again in the route dependency `Depends(get_current_user)`. That's 2× the JWKS fetch overhead per authenticated call.
- ⚠️ **In-process storage** (comment on line 23 admits this). Any horizontal scaling multiplies the effective limit. Needs Redis backend before adding a second worker.
- ⚠️ Any tampered token raises an exception here BEFORE the route runs, which is what the docstring intends, but it means the 401 is thrown from the rate-limit layer, not from `get_current_user` — the error handler path is subtly different.

### 4.3 AI/Parsing (`chatbot/`, `parsing/`)

#### `chatbot/chat_service.py` (102 lines) — **Update**
**Does:** Async Groq client using `openai/gpt-oss-20b`. Long system prompt encodes Whofy product knowledge and topic restrictions.
- ⚠️ **New `AsyncGroq` client created on every request** (line 80) — no connection reuse. `parsing/resume_parser.py` correctly uses a singleton via `_get_groq_client()`. Inconsistent.
- ⚠️ System prompt contains factual claims ("20,000+ live job listings", specific source list). This drifts from DB reality every day. Product facts should be pulled from settings/DB or a stats endpoint.
- ⚠️ No timeout on the Groq call. `parsing/` uses `GROQ_TIMEOUT = 30`; here it's unbounded.
- ⚠️ No semaphore. `parsing/` limits to 3 concurrent LLM calls; chat has none.

#### `chatbot/router.py` (19 lines) — **Update**
**Does:** `POST /api/chat`, validates non-empty message, calls `get_chat_response`.
- ⚠️ **No rate limit** — every request hits paid Groq API. This was called out as F-09 P1 and remains open.
- ⚠️ **Unbounded `history: list[dict] = []`** — a 100k-item history is happily forwarded to Groq. Cap history length + total characters.
- ⚠️ No response model.

#### `parsing/resume.py` (68 lines) — **Keep**
**Does:** `POST /api/upload-resume`, extension guard, chunked read with 5MB cap, sanitized error responses for `UnsupportedFileType`/`EmptyResumeText`/`NotAResume`.
- ✅ Correct chunked read (8KB, hard stop at 5MB) — no reliance on client-provided `file.size`.
- ✅ Rate-limited (`5/minute`).
- ✅ Sanitized errors, no leaked internals.
- 📝 `PARSING_AUDIT.md` documented all 18 findings and they're all applied. This file is a good template for how other AI endpoints (chat) should look.

#### `parsing/resume_parser.py` (180 lines) — **Keep**
**Does:** Magic-byte validation, PDF (PyMuPDF) + DOCX (with tables) extraction, singleton `AsyncGroq`, semaphore-limited (max 3), 30s timeout, Pydantic `ResumeResult` validation, `NotAResume` rejection when `isResume=False` or skills empty, system/user prompt split with anti-injection wrapper.
- ✅ Reference implementation for how LLM endpoints in this codebase should be built.
- ⚠️ Minor: `ResumeResult` fallback on line 159 silently truncates malformed shapes to defaults — logs a warning but returns unvalidated `skills`. That's tolerant but could mask bugs.

### 4.4 Ingestion — Runners

#### `listings/run_api.py` (129 lines) — **Refactor** (also has P1 correctness issues)
**Does:** Runs 6 API sources concurrently. Monkey-patches `ThreadPoolExecutor.submit` to propagate `ContextVars`. `ThreadPrefixLogger` injects `[source]` prefix on every stdout line. Shared `ProcessPoolExecutor` sized by CPU. Semaphore limits "heavy" sources (Greenhouse/Lever/Ashby) to 2 in flight. Runs `cleanup_expired_jobs` + `cleanup_non_english_jobs` + stats after.
- ⚠️ **F-03 P0 STILL OPEN:** `run_source_concurrently` catches `Exception`, prints, returns nothing. `future.result()` on line 109 sees a happy future. **Ingestion can fully fail one or more sources and CI stays green.** Return a `SourceRunResult`; abort cleanup if any critical source failed.
- ⚠️ Cleanup runs after the API stage AND after the scraper stage (in `run_scrapper.py`). Both runs do the same `cleanup_expired_jobs` twice per daily job.
- ⚠️ Duplicated with `run_scrapper.py` (see below).
- ⚠️ Monkey-patching `ThreadPoolExecutor.submit` is a global side effect that will surprise anyone.
- ⚠️ `sys.stdout = logger` replaces process stdout. If an unhandled exception fires after replacement, tracebacks go through the prefix logger.

#### `listings/run_scrapper.py` (113 lines) — **Refactor**
**Does:** Same shape as `run_api.py` but runs 3 scraper sources (Workday, WWR, HN — LinkedIn commented out).
- ⚠️ **Nearly-identical copy-paste** of `run_api.py`: monkey-patch, logger class, semaphore, `run_source_concurrently`. Consolidate into a single `runner.py` that takes a config.
- ⚠️ Does NOT create a shared `ProcessPoolExecutor` — the scraper sources don't use `process_jobs_batch` anyway. This is because Workday/WWR/HN do their enrichment inline in the fetcher (violates `INGESTION_ARCHITECTURE.md` — see F-12).
- ⚠️ Same F-03 swallowed-failure issue.
- ⚠️ LinkedIn is commented out (line 82) rather than represented as a disabled source with health state.

#### `ingest_api.py` / `ingest_scrapper.py` (7 lines each) — **Keep**
Two-line thin entrypoints that `load_dotenv()` and call the runner. Fine as-is. Only nit: they should propagate a non-zero exit code when the runner reports failures — which the runner currently doesn't.

### 4.5 Ingestion — Provider Fetchers

**Pattern that all API-based fetchers should follow** (Greenhouse is the reference):
1. Fetch raw pages via `requests` (thread-parallel).
2. Map into a raw dict with keys `source`, `source_job_id`, `title`, `company`, `location`, `raw_description`, `apply_url`, `posted_at`.
3. Hand to `process_jobs_batch(jobs, mp_executor=mp_executor)` which does normalization/enrichment/filtering in a shared ProcessPoolExecutor.
4. `save_jobs(accepted_jobs, source=...)`.

**Common issues across every fetcher:**
- Every fetcher imports `bake_required_skills, detect_experience, detect_work_type, extract_required_skills, filter_tech_jobs` from shared modules but the ones that hand off to `process_jobs_batch` **never call them** — the pipeline handles it. Dead imports. Cleanup opportunity.
- All hardcode their `COMPANIES` list as a Python constant. Adding a company = code change + deploy.

Individual notes:

#### `listings/greenhouse/fetcher.py` (273 lines) — **Keep** (with cleanup)
- ✅ Reference implementation. 170 companies. Correct handoff to `process_jobs_batch`.
- ⚠️ Dead imports (bake_required_skills, detect_*, extract_*, filter_tech_jobs — never called after refactor).
- ⚠️ Profiling `print()` calls only fire for source `"greenhouse"` (storage.py:343). Leave or remove.

#### `listings/lever/fetcher.py` (129 lines) — **Keep** (with cleanup)
- ✅ Correct handoff. Correctly sets `data_quality_flags=["missing_posted_at"]` (Lever API doesn't expose date).
- ✅ Passes provider-native `work_type` when available.
- ⚠️ Same dead imports.

#### `listings/ashby/fetcher.py` (167 lines) — **Keep** (with cleanup)
- ✅ Correct handoff. Handles both `descriptionHtml` and `description` fallback.
- ⚠️ Same dead imports.

#### `listings/remoteok/fetcher.py` (80 lines) — **Keep** (with cleanup)
- ✅ Minimal, clean. Correct handoff.
- ⚠️ Same dead imports.

#### `listings/adzuna/fetcher.py` (241 lines) — **Update**
- ✅ Retry with exponential backoff on 429/5xx. Raises `RateLimitExhausted` after `MAX_RETRIES`.
- ⚠️ **F-15 STILL OPEN:** 3 worker threads × 1s delay ≠ 3 rps global. The per-thread sleep does not enforce Adzuna's daily quota. Should be a shared token bucket.
- ⚠️ **F-21 STILL OPEN:** `executor.shutdown(wait=False, cancel_futures=True)` inside `with ThreadPoolExecutor(...)` — context exit still waits for running work.
- ⚠️ 12 countries × 55 queries = 660 tasks queued up front; can't stop early.

#### `listings/adzuna/fetcher_test.py` (193 lines) — **Delete**
- ⚠️ **Not a test.** A near-duplicate of `adzuna/fetcher.py` with an `in_flight` counter, `US`-only country list, only 6 queries. Uses live API. Prints "Skipping save for test" at the end.
- ⚠️ Duplicating production logic in an environment named `_test.py` creates confusing search results and diverges immediately. Delete it. Replace with mocked-response unit tests under `tests/`.

#### `listings/himalayas/fetcher.py` (173 lines) — **Update**
- ✅ Fetches paginated with retry backoff. Filters by 30-day age at fetch time.
- ⚠️ **F-21:** same cancellation pattern as Adzuna.
- ⚠️ Enqueues all offsets up-front before it knows whether it can stop early.

#### `listings/hackernews/fetcher.py` (203 lines) — **Update**
- ✅ Nice header parser (`_parse_header`) that pulls company/title/location/work_type from HN post format.
- ⚠️ **F-12 STILL OPEN:** does enrichment inline (`extract_required_skills`, `detect_work_type`, `detect_experience`, `bake_required_skills` all called in `fetch_hn_jobs`), then calls `filter_tech_jobs` before save. Bypasses `process_jobs_batch`.
- ⚠️ Sequential HTTP calls with `REQUEST_DELAY = 0.3` — a "Who is hiring" thread with 900 comments takes 4.5 minutes just for the sleep.

#### `listings/scraping/weworkremotely/fetcher.py` (142 lines) — **Update**
- ✅ RSS parsing, correct date handling with `parsedate_to_datetime`.
- ⚠️ **F-12:** same inline-enrichment pattern.
- ⚠️ `posted_at` is stored as an ISO **string**, not a `datetime` — inconsistent with the API fetchers and hits `_is_too_old`/model validation edge cases (see F-04).

#### `listings/scraping/workday/fetcher.py` (275 lines) — **Update (bug)**
- ⚠️ **F-14 P1 STILL OPEN:** lines 235 and 238 both write to `description` in the same dict literal:
  ```python
  "description": bake_required_skills(title, required_skills),  # line 235
  ...
  "description": None,                                          # line 238
  ```
  Python keeps the last value. **Every Workday job ends up with `description=None`.** The `bake_required_skills(title, ...)` result is discarded.
- ⚠️ **F-12:** inline enrichment, `filter_tech_jobs` before save. Bypasses `process_jobs_batch`.
- ⚠️ `posted_at` is stored as string (`_posted_at_from_age` returns `.isoformat()`), not datetime.
- ⚠️ 27 Workday companies hardcoded.

#### `listings/scraping/linkedin/fetcher.py` (302 lines) — **Update (currently disabled)**
- ⚠️ **F-13 P1 STILL OPEN:** `_parse_search_page` sets `posted_at` as a `datetime` (line 135), but `_is_within_age` on line 79–89 expects a string and calls `.replace("Z", "+00:00")` on it. TypeError caught silently → returns `True` → all jobs pass. Then `_enrich_listings` line 259 calls `.replace("Z", "+00:00")` on the datetime again — this one is NOT in a try/except and will crash the scraper.
- ⚠️ Commented out of `run_scrapper.py` (line 82). It should be represented as a source with a `disabled` flag, not hidden in a comment.
- ⚠️ Guest-scraping LinkedIn is legally/ToS ambiguous; keep it disabled until that's cleared.
- ⚠️ ~8 locations × 20 queries × 8 pages × sequential detail fetches × `REQUEST_DELAY=1.2` ≈ 50 minutes when re-enabled (as `SPEC.md` §7 notes).

### 4.6 Ingestion — Shared

#### `listings/shared/storage.py` (480 lines) — **Refactor** (highest-risk file)
This is the load-bearing file for the entire ingestion write path. It's also where the P0 findings live.
- ⚠️ **F-01 P0:** `cleanup_expired_jobs` (line 429) builds `cutoff = (...)isoformat()` — a string — and compares with `$lt` against BSON date fields. MongoDB comparisons are type-sensitive; the query mostly won't delete what it should, and could delete surprising things depending on how documents look. Use timezone-aware `datetime` directly.
- ⚠️ **F-01 P0:** Cleanup deletes by `added_at`, not `last_seen_at`. A job seen today but ingested 40 days ago is deleted. Semantic bug.
- ⚠️ **F-04 P1:** `_is_too_old(posted_at: str)` (line 221) calls `posted_at.replace("Z", "+00:00")`. Greenhouse/Ashby/Adzuna/RemoteOK/HN pass `datetime` objects. The `TypeError` is caught by the broad `except`, function returns `False`, meaning "not too old" → old jobs accepted.
- ⚠️ **F-05 P1:** `_fingerprint(source, source_job_id)` includes source in the fingerprint. Two providers listing the same job produce different fingerprints. The cross-source query on line 277–280 excludes `source: {"$ne": source}` — so it's checking whether a fingerprint from source A exists in source B, but since fingerprints include source, it never finds cross-source matches. `cross_source_skipped` counter is misleading.
- ⚠️ **F-19 P2:** Line 301 `try...except Exception as e: schema_rejected += 1; continue` — no quarantine document, no sample payload, no error reason preserved. If Greenhouse changes its schema, we lose the record silently.
- ⚠️ **F-22 P2:** `_client_instance` global (line 24) creates a separate MongoClient bypassing `db/mongo.py`. Two singletons, two pools, two lifecycle owners.
- ⚠️ **Dead code:** `is_link_alive`, `filter_dead_links`, `normalize_existing_locations` — no callers anywhere.
- ⚠️ `MONGODB_URI = settings.mongodb_uri` at line 15 (module top) is read once at import time. If settings load later, this is `None`.
- ⚠️ Greenhouse-only profiling `if source == "greenhouse"` on line 343 is debug leftover.
- ⚠️ Location normalization dictionaries (`COUNTRY_CODE_MAP`, `KNOWN_CITIES`, state name list) are correct but should be data files, not code.
- ✅ Language cleanup with ProcessPoolExecutor + `lang_checked` flag is a genuine win — cleanup went from 4 minutes to 0.07s per SPEC.
- ✅ `ensure_indexes` idempotently defines the 7 indexes.

#### `listings/shared/pipeline.py` (105 lines) — **Keep** (small update)
**Does:** `process_single_job` runs tech filter → language filter → skill/work-type/experience enrichment → `bake_required_skills`. `process_jobs_batch` uses ProcessPoolExecutor for batches ≥ 300, sync for smaller ones.
- ✅ Small-batch fallback (< 300 jobs) is measured and correct — pickling overhead beats speedup for small batches.
- ⚠️ `process_single_job` type annotation says `dict | None` but never returns None — returns the dict with `filtered_reason` set to `"tech"` / `"lang"` / `None`. Update annotation.
- ⚠️ Broad `try/except` around `detect(text)` in `_is_non_english` swallows all exceptions and returns `False`. A `LangDetectException` is expected; other exceptions should be logged.

#### `listings/shared/enrich.py` (380 lines) — **Keep**
**Does:** 900+ term skill vocabulary, two compiled regexes (case-sensitive for short/ambiguous terms like "C", "R", "Go", case-insensitive for the rest), `extract_required_skills` (max 15), `detect_work_type`, `detect_experience` (years-of-experience heuristics), `bake_required_skills` (appends `Required skills: • X • Y` block to description).
- ✅ Well-organized, comment above `SKILL_VOCAB` gives a rule for adding new terms.
- ✅ `_CASE_SENSITIVE_SKILLS` (line 283) correctly separates ambiguous short terms.
- ⚠️ 900-term regex is expensive to compile (once) and heavy to run on 30k+ jobs — this is CPU-bound and one reason ingestion uses ProcessPoolExecutor. Fine.
- ⚠️ Vocabulary is a code file, not data. Reviewing/expanding requires a code change + deploy.
- ⚠️ `detect_experience` fallback of `"Mid Level"` when no signal detected is opinionated; many "junior with no year mentioned" jobs will be mislabeled.

#### `listings/shared/normalize.py` (101 lines) — **Keep**
**Does:** `_unescape` (multi-pass HTML entity decode), `_parse_lines` (block-level HTML → line list), `strip_html` (used everywhere; summarizes to intro paragraph + first 5 bullets), `full_text` (loss-less line join), `first_paragraph`, `extract_bullets`.
- ✅ Small, well-scoped, has a `_summarize` helper that keeps output bounded.
- ⚠️ `strip_html` is not a sanitizer — the docstring should say so. Its purpose is UI-friendly summary text.
- ⚠️ Malformed HTML edge cases aren't fixtured.

#### `listings/shared/tech_filter.py` (77 lines) — **Keep**
**Does:** Regex whitelist (~40 tech-adjacent role patterns) + blacklist (~35 explicitly-not-tech roles). `is_tech_job(title, description)`: blacklist-in-title → reject; whitelist-in-title → accept; whitelist-in-first-500-chars-of-description → accept.
- ✅ Deterministic and fast.
- ⚠️ Title/description-head only — heuristic. Track filter reason and periodically sample false positives.
- ⚠️ `filter_tech_jobs` (line 76) is used only by the four inline-enrichment scrapers (LinkedIn, WWR, Workday, HN). Once those move to `process_jobs_batch`, this function becomes dead.

#### `listings/shared/logos.py` (181 lines) — **Keep** (minor update)
**Does:** Known-domain map for 80+ well-known companies, guess `{slug}.com` otherwise, HEAD Clearbit `logo.clearbit.com/{domain}` in parallel (10 workers), cache result (URL or `None`) in `company_logos` collection.
- ✅ Caches negative results — subsequent runs don't refetch.
- ⚠️ Blocking `requests.head` per company; timeout of 5s. A bad DNS day could stretch this.
- ⚠️ Failures make ingestion slower but don't break it (`attach_logos` returns 0). Good failure mode.
- ⚠️ 80-line hardcoded domain map lives in code.

### 4.7 Pipeline utility scripts (`pipeline/`)

#### `pipeline/audit_indexes.py` (27 lines) — **Update (broken for anyone else)**
- ⚠️ **Line 6: `sys.path.insert(0, r"c:\Users\chara\Desktop\whofy\whofy-api")`** — hardcoded path from another developer's machine. On any other machine this line is a no-op (path doesn't exist) but is misleading.
- ⚠️ Never closes the Mongo client.

#### `pipeline/backfill_enrichment.py` (39 lines) — **Keep**
- ✅ Sensible full-collection backfill via `UpdateOne` + `bulk_write`.
- ⚠️ Loads all operations into memory (fine at 46k docs; not fine at 1M).
- ⚠️ No dry-run flag, no `--only-missing` filter.

#### `pipeline/backfill_fingerprints.py` (54 lines) — **Update**
- ⚠️ **Line 6: same hardcoded `c:\Users\chara\Desktop\...` path.**
- ✅ Otherwise correct — batches writes, closes the client.

#### `pipeline/cleanup.py` (18 lines) — **Keep**
- Thin wrapper around `cleanup_expired_jobs` + stats. Inherits F-01 through it though (same broken date semantics as `storage.py`).

#### `pipeline/fix_duplicate_skills.py` (50 lines) — **Keep** (or delete post-fix)
- ✅ One-time migration to strip duplicate "Required skills:" blocks from descriptions.
- ⚠️ Once run against prod and confirmed cleared, this can be deleted.
- ⚠️ Loads all ops in memory (fine at current scale).

### 4.8 Tests

#### `test_rate_limit.py` (root, 22 lines) — **Delete**
- Prints only; no assertions. Requires a running server on `localhost:8001`. Not a test.

#### `test_rate_limit_auth.py` (root, 60 lines) — **Delete**
- Uses `dependency_overrides` and `TestClient` — closer to a real test — but has zero `assert` statements. Prints results.

#### `tests/fixtures/.gitkeep` — **Keep** (as folder marker; add real tests)
- The literal entire test suite. Populate with provider payload fixtures.

### 4.9 Root scripts

#### `generate_audit_outputs.py` (67 lines) — **Delete**
- Windows-only diagnostic (uses `findstr /S /R`), hardcoded query patterns, live DB EXPLAIN calls. Ad hoc, not maintained, doesn't close the async client. Nuke.

### 4.10 CI / Config / Meta

#### `.github/workflows/ingestion.yml` (36 lines) — **Update**
- ✅ Pinned Python 3.12, pip cache, 60-minute timeout, concurrency group prevents overlap.
- ⚠️ Runs `ingest_api.py` then `ingest_scrapper.py` sequentially — cleanup fires twice.
- ⚠️ Both stages run unconditionally: if `ingest_api.py` swallows failures (F-03) and the scraper stage runs cleanup, we can delete jobs after a partial run.
- ⚠️ No lint / type-check / test steps.
- ⚠️ Uses `actions/setup-python@v6` (pre-release) — pin to `@v5` unless there's a reason.

#### `.gitignore` (7 lines) — **Update**
- ✅ Ignores `.venv/`, `__pycache__/`, `*.pyc`, `.env`, `node_modules/`, `scratch/`, `test_resume/`.
- ⚠️ But `__pycache__/main.cpython-312.pyc` and `matching/__pycache__/ranker.cpython-312.pyc` are **tracked** in git — they were committed before `.gitignore` covered them. Run `git rm -r --cached __pycache__ matching/__pycache__` and commit.

#### `.env.example` (7 lines) — **Keep**
- ✅ Accurate list of the 7 keys used by `config/settings.py`.
- Minor: no comment about which are required vs optional per environment (dev/prod).

#### `.env` — **Not audited**
- Real secrets; correctly gitignored. Left unread.

#### `.vscode/settings.json` — **Update**
- ⚠️ File is UTF-16 encoded (BOM `FF FE`) with escaped backslashes — someone saved it via PowerShell `Out-File` without `-Encoding utf8`. Re-save as UTF-8. Content itself (`python.defaultInterpreterPath`) is trivially correct.

#### `requirements.txt` (15 pinned deps) — **Update**
- ✅ Every dep is pinned to an exact version. Good baseline for reproducibility.
- ⚠️ No `pyproject.toml`, no `uv.lock`/`pip-tools` export with hashes, no dev/test separation, no Dockerfile.
- ⚠️ `certifi` is used by `storage.py:3` and `mongo.py:3` but is not in `requirements.txt` — it's pulled transitively by `requests`. Add it explicitly.

### 4.11 Dead directories / files

#### `matching/` — **Delete**
- Contains only `__pycache__/ranker.cpython-312.pyc` from July 2025. No `.py` source, no `__init__.py`. Prior audits claimed it was deleted; it was not. Nuke.

#### `__pycache__/` (root, contains `main.cpython-312.pyc`) — **Untrack, delete**
- Should not be in the tree. `git rm -r --cached __pycache__/` and confirm `.gitignore` covers it.

#### `tests/` (only holds `fixtures/.gitkeep`) — **Keep, populate**
- Placeholder is fine; there just isn't a suite yet.

---

## 5. Cross-Cutting Themes

### 5.1 What was already fixed (per `SPEC.md`) and verified in code

| Fix | Verified |
|---|---|
| CI/CD split into `ingest_api.py` + `ingest_scrapper.py` | ✅ Confirmed in `.github/workflows/ingestion.yml` |
| Cleanup optimization (`lang_checked` flag + ProcessPoolExecutor) | ✅ Confirmed in `storage.py` `cleanup_non_english_jobs` |
| Deps trimmed (`python-jose`, `authlib`, `httpx` removed) | ✅ Not in `requirements.txt` |
| `.env.example` cleaned | ✅ Reflects current settings |
| Adzuna + Himalayas parallelized | ✅ Both use ThreadPoolExecutor |
| Parsing module hardened (all 18 findings) | ✅ Confirmed against `parsing/resume_parser.py` |

### 5.2 What `SPEC.md` / prior `AUDIT.md` claimed but is NOT true

| Claim | Reality |
|---|---|
| `matching/`, `sources/`, `models/` were deleted | `matching/` still exists (only a `.pyc`). `models/` still exists and is actively used. Only `sources/` and `config/sources.py` were actually removed. |
| `node_modules/` cleaned up | Correctly cleaned (verified: not present). |
| Backfill script typos fixed | Fixed — but the hardcoded `c:\Users\chara\Desktop\...` paths remain in `audit_indexes.py` and `backfill_fingerprints.py`. |
| "Critical weaknesses like broken CI/CD, cleanup, dead folders resolved" | Cleanup pipeline was fixed. Everything else in the "Remaining Scalability Concerns" list of the old AUDIT is still open. |

### 5.3 P0/P1 findings from `CODE_REVIEW_ARCHITECTURE_AUDIT.md` — status

**Updated 2026-08-11:** Phase 0 fix pass cleared most P0/P1 blockers. Remaining items are P1-P3 with lower urgency.

| ID | Sev | Status | Location | Fix summary |
|---|---|---|---|---|
| F-01 | P0 | ✅ **DONE 2026-08-11** | `listings/shared/storage.py:434` | Uses datetime cutoff + `last_seen_at`. Cleanup verified working (0 stale rows currently). |
| F-02 | P0 | ⏸ **DEFERRED** | `fetch_api/auth.py:54–81` | Pass `issuer=` and `audience=` to `jwt.decode` — needs Clerk dashboard values |
| F-03 | P0 | ✅ **DONE 2026-08-11** | `listings/run_api.py`, `run_scrapper.py` | Returns `SourceRunResult`, skips cleanup on failure, `sys.exit(1)` → CI red → email |
| F-04 | P1 | ✅ **DONE 2026-08-11** | `listings/shared/storage.py:221` | `_is_too_old` accepts `str \| datetime \| None` |
| F-05 | P1 | ⬜ Open | `listings/shared/storage.py:35–37` | Separate `source_key` from `canonical_fingerprint` — needs data model work |
| F-06 | P1 | ✅ **DONE 2026-08-11** | `fetch_api/saved_jobs.py` | ObjectId validated at top of route; 400 on invalid |
| F-07 | P1 | ✅ **DONE 2026-08-11** | `fetch_api/saved_jobs.py`, `storage.py` | Unique index `(user_id, job_id)` + atomic upsert with `$setOnInsert` |
| F-08 | P1 | ✅ **DONE 2026-08-11** | `fetch_api/saved_jobs.py` | `skip`/`limit` pagination + `{jobs,total,skip,limit}` envelope; `str(id)` on expired branch |
| F-09 | P1 | ✅ **DONE 2026-08-11** | `chatbot/router.py`, `chat_service.py` | 20/min rate limit + 3000-char message cap + 30-entry history cap + singleton Groq client |
| F-11 | P1 | ✅ Done (prior) | `parsing/resume_parser.py` | Pydantic validation of Groq output |
| F-12 | P1 | ⬜ Open | `listings/hackernews/`, `scraping/weworkremotely/`, `scraping/workday/`, `scraping/linkedin/` | Move inline enrichment into `process_jobs_batch` |
| F-13 | P1 | ⬜ Open | `listings/scraping/linkedin/fetcher.py` | Fix datetime handling before re-enable (LinkedIn stays disabled) |
| F-14 | P1 | ✅ **DONE 2026-08-11** | `listings/scraping/workday/fetcher.py:235` | Removed duplicate `description: None` key |
| F-15 | P1 | ⬜ Open | `listings/adzuna/fetcher.py` | Global token-bucket limiter (also applies to Himalayas — 429s observed in prod) |
| F-16 | P1 | ⬜ Open | `fetch_api/jobs.py` | Short-TTL cache for `distinct()` endpoints; reduce max page sizes |
| F-17 | P2 | ⏸ **DEFERRED** | `fetch_api/auth.py:19–30` | Async HTTP client + TTL cache + refresh lock (part of the JWT block) |
| F-18 | P2 | ⬜ Open | `fetch_api/limiter.py:20–24` | Redis storage before adding replicas |
| F-19 | P2 | ⬜ Open | `listings/shared/storage.py:301–333` | `ingestion_rejections` collection for observable schema failures |
| F-20 | P2 | ✅ **DONE 2026-08-11** | `listings/shared/storage.py:434` | Cleanup now uses `last_seen_at` |
| F-21 | P2 | ⬜ Open | Adzuna/Himalayas | Bounded producer/consumer; drop `shutdown(wait=False)` inside `with` |
| F-22 | P2 | ⬜ Open | `db/mongo.py` vs `storage.py` | Single MongoDB access module (still two singletons) |
| F-23 | P2 | ⬜ Open | `test_rate_limit*.py`, `adzuna/fetcher_test.py`, `tests/` | Real assertion-based tests |
| F-24 | P2 | ⬜ Open | Root | `pyproject.toml` + lockfile + Dockerfile |
| F-25 | P3 | ⬜ Open | Both runners | Consolidate into one runner |
| F-26 | P3 | ⬜ Open | Every fetcher | Move `COMPANIES` to config |
| F-27 | P3 | ⬜ Open | `main.py:42` | `/api/ready` with Mongo + JWKS checks |
| F-28 | P3 | ✅ Done | — | This doc supersedes prior stale claims |

### 5.4 New findings surfaced by this audit (not in prior docs)

| # | Sev | Status | Finding | Where |
|---|---|---|---|---|
| N-01 | P3 | ✅ **DONE 2026-08-11** | Hardcoded `c:\Users\chara\Desktop\whofy\whofy-api` paths — removed | `pipeline/audit_indexes.py`, `pipeline/backfill_fingerprints.py` |
| N-02 | P3 | ✅ **DONE 2026-08-11** | `matching/` directory (only a stale `.pyc`) — deleted | `matching/` gone |
| N-03 | P3 | ⏭️ Skipped by user | `__pycache__/main.cpython-312.pyc` tracked at repo root | `__pycache__/` |
| N-04 | P3 | ⬜ Open | `.vscode/settings.json` is UTF-16 encoded with escape junk (PowerShell `Out-File`) | `.vscode/settings.json` |
| N-05 | P2 | ⬜ Open | Dead imports of `detect_experience`, `detect_work_type`, `extract_required_skills` in `fetch_api/jobs.py:10` — never called | `fetch_api/jobs.py:10` |
| N-06 | P2 | ⬜ Open | Dead functions `is_link_alive`, `filter_dead_links`, `normalize_existing_locations` in `storage.py` — no callers | `storage.py:40,49,411` |
| N-07 | P2 | ⬜ Open | Every fetcher imports enrichment helpers at top but those using `process_jobs_batch` never call them | All `listings/*/fetcher.py` |
| N-08 | P2 | ⬜ Open | `certifi` used by `storage.py:3` + `mongo.py:3` but not in `requirements.txt` (pulled transitively) | `requirements.txt` |
| N-09 | P2 | ✅ **DONE 2026-08-11** | Chatbot now uses singleton `AsyncGroq` client (matches `parsing/resume_parser.py:111`) | `chatbot/chat_service.py` |
| N-10 | P2 | ⬜ Open | Chatbot system prompt hardcodes drifting product facts ("20,000+ live job listings", source list) | `chatbot/chat_service.py:26–71` |
| N-11 | P2 | ⬜ Open | LinkedIn disabled via **comment** in `run_scrapper.py`, not as a source with `enabled=False` state | `listings/run_scrapper.py:82` |
| N-12 | P2 | ⬜ Open | WWR + Workday store `posted_at` as **strings** while API fetchers store `datetime` — inconsistent typing | Both scraper `fetcher.py` files |
| N-13 | P3 | ⬜ Open | `_JWKS_CACHE["keys"]` stores the entire JWKS JSON (not just `.keys`) — confusing naming | `fetch_api/auth.py:29` |
| N-14 | P3 | ⬜ Open | `settings.mongodb_uri` read at import time in `storage.py:15` | `storage.py:15` |
| N-15 | P3 | ⬜ Open | Greenhouse-only profiling `print()` left in `save_jobs` from a benchmark | `storage.py:343–352` |
| N-16 | P3 | ⬜ Open | Cleanup runs twice per GH Action run (once after each ingest stage) | `run_api.py`, `run_scrapper.py`, `ingestion.yml` |
| **N-17** | **P2** | ⬜ **Open (new — logged 2026-08-11)** | **Company logo pipeline shows generic globe icons on results page for many companies.** Backend confidently returns `https://google.com/s2/favicons?domain=<guessed>&sz=128` for jobs whose sources don't supply `company_domain` (Adzuna, RemoteOK). Google's favicon API returns a placeholder globe for unknown domains — the `<img>` "loads successfully" so the frontend `onError` fallback (colored letter) never fires. User sees a generic globe for companies like Trigent Software, DATAECONOMY, Knit Finance, etc. **Two fixes:** (a) short-term — stop returning Google favicon URLs when domain was guessed rather than known; let frontend show the colored-letter fallback. (b) long-term — auto-populate `logos.py` `KNOWN_DOMAINS` from the existing `COMPANIES` domain data already present in Greenhouse/Ashby/Lever/Workday/Himalayas fetchers; consider switching Clearbit → Logo.dev or Brandfetch. | `fetch_api/jobs.py:42–48`, `listings/shared/logos.py`, `listings/adzuna/fetcher.py`, `listings/remoteok/fetcher.py` |
| **N-18** | **P1** | ✅ **DONE 2026-08-11 (root cause of "unsave broken" symptom)** | **`PyObjectId` serializer converted `ObjectId` → `str` on `model_dump()`**, meaning `SavedJob.model_dump(by_alias=True)` stored `job_id` as a string in MongoDB. All saved-jobs docs had string-typed `job_id`, so DELETE queries (which used `ObjectId`) never matched → 404 on every unsave. Added `when_used='json'` so serialization only fires on JSON output, not on Python dicts destined for Mongo. Migrated by wiping the small saved_jobs collection (2 records). | `models/job.py:15–19` |

---

## 6. Prioritized Action List

### Phase 0 — Do before next production ingestion (blockers)

**Status after 2026-08-11 fix pass: 6 of 7 items complete.**

1. ✅ **DONE** — F-14 Workday duplicate `description` key (line 238 removed)
2. ✅ **DONE** — F-01 / F-04 / F-20 date semantics in `storage.py` (normalizer, datetime cutoff, `last_seen_at`)
3. ✅ **DONE** — F-03 swallowed source failures (`SourceRunResult`, skip cleanup on fail, `sys.exit(1)`)
4. ⏸ **DEFERRED** — F-02 JWT `iss`/`aud` + F-17 async JWKS. Waiting on Clerk dashboard values from user. 5-minute fix once values are known.
5. ✅ **DONE** — F-06 / F-07 / F-08 saved-jobs (ObjectId validation, unique index, atomic upsert, pagination envelope, str-serialized IDs, plus N-18 serializer fix and UI wire-up)
6. ✅ **DONE** — F-09 chatbot (20/min rate limit, 3000-char message cap, 30-entry history cap, singleton Groq client via N-09)
7. ✅ **DONE (partial)** — N-01 hardcoded paths purged, N-02 `matching/` deleted. N-03 (untrack `__pycache__/`) explicitly skipped by user, N-04 (`.vscode/settings.json` encoding) left open.

### Phase 1 — Make behavior testable

8. Delete `test_rate_limit.py`, `test_rate_limit_auth.py`, `adzuna/fetcher_test.py`, `generate_audit_outputs.py`. Replace with mock-based tests under `tests/unit/`, `tests/contract/`, `tests/integration/`.
9. Add provider parser fixtures (one representative payload per source) so schema regressions surface in CI.
10. Add JWT tests once F-02 lands: wrong issuer, wrong audience, expired, unknown kid, missing sub, key rotation.
11. Add saved-jobs tests: invalid ID, duplicate write, pagination, expired snapshot, upsert-race safety (should pass after F-07 fix).
12. Add cleanup tests: native datetime, missing date, active-but-old, failed-source-run gating (should pass after F-01/F-03 fixes).
13. Add chatbot tests: request oversize rejection, history cap rejection, per-user rate-limit isolation.

### Phase 2 — Structural cleanup

14. **Company logo pipeline overhaul (N-17)** — stop returning Google favicon URLs for guessed domains; auto-populate `logos.py` `KNOWN_DOMAINS` from the fetcher `COMPANIES` lists; evaluate swapping Clearbit for Logo.dev or Brandfetch.
15. Consolidate `run_api.py` + `run_scrapper.py` into one runner driven by a source registry. Represent LinkedIn as `enabled=False` (N-11) not a comment.
16. Move Workday/WWR/HN/LinkedIn to fetch-only adapters that hand off to `process_jobs_batch` (F-12).
17. Extract enrichment vocabulary + tech filter regex to data files; extract company lists (Greenhouse/Lever/Ashby/Workday/Adzuna) to a `sources.yml` (F-26).
18. Split `db/mongo.py` and `storage.py` to share one MongoDB access module (F-22). One `_client_instance`, one pool policy, one shutdown owner.
19. Break `models/job.py` into `domain/` (persistence) and `api/dto/` (responses). Stop importing enrichment from API layer (N-05).
20. Add `pyproject.toml` + lockfile + Dockerfile (F-24).
21. Add `.dockerignore`, add `certifi` to requirements (N-08), delete tracked `__pycache__/` (N-03), fix `.vscode/settings.json` encoding (N-04).
22. Cross-source dedup (F-05) — separate `source_key` from `canonical_fingerprint`; log candidates before making it a delete rule.

### Phase 3 — Scale readiness

23. Redis-backed SlowAPI storage before running >1 uvicorn worker or >1 replica (F-18).
24. Short-TTL cache for `/api/locations`, `/api/companies`, `/api/sources` (F-16).
25. Reduce max page sizes; add MongoDB explain-plan review under realistic data volume.
26. Move ingestion to a separate worker process (already effectively is — just make it a proper service).
27. Global token-bucket rate limiter for Adzuna and Himalayas (F-15, F-21) — 429s observed in production Himalayas run 2026-08-11.
28. `ingestion_rejections` collection for schema-rejected job payloads (F-19).
29. `/api/ready` endpoint distinct from `/api/health` — pings Mongo and JWKS (F-27).

---

## 7. What This Audit Did Not Cover

- **`.env` contents:** not opened. Credentials assumed valid; rotation status unverified.
- **Live database:** no queries run. Document counts, index usage stats, and query plans are not re-verified from prior audits.
- **Provider behavior:** each fetcher's target API/scrape target was not exercised. Payload assumptions rely on `AUDIT_DATA_POINTS.md`.
- **Runtime performance:** no profiling. Bottleneck claims (LinkedIn ~50min, Greenhouse enrichment) are quoted from `SPEC.md`.
- **Legal/ToS review** of LinkedIn/Workday scraping.
- **Frontend integration** (out of scope per user instruction).
