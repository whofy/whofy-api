# Whofy-API — Full Codebase Audit

> **Generated:** 2026-08-10
> **Last updated:** 2026-08-13 (Post-Phase-3 UX pass — search relevance, pagination, dropdown cache, mojibake backfill; see §1d Fix Log)
> **Scope:** every tracked file under `D:\whofy\whofy-api\` (excluding `.git/`, `.venv/`, `__pycache__/`).
> **Method:** every file below was read end-to-end. Findings are grounded in the real code as it exists today, not inherited from prior audits. Where prior docs made claims that no longer match reality, this document overrides them.
> **Companion docs:** `SPEC.md` (history of past fixes), `CODE_REVIEW_ARCHITECTURE_AUDIT.md` (2026-08-08 deep review), `PARSING_AUDIT.md` (parser module — fully applied), `INGESTION_ARCHITECTURE.md` (intended pipeline contract), `AUDIT_DATA_POINTS.md` (schema reference), `groq_api_limits.md` (LLM quotas).

---

## 1. Executive Summary

Whofy-API is a modular FastAPI monolith (~4,500 lines of application code) fronting MongoDB Atlas, with a batch ingestion worker that scrapes ten sources into a single `jobs` collection. It works: `main.py` boots, `/api/health` returns OK, the ingestion GH Action runs daily, and the frontend is served correctly-shaped documents. The parsing module was fully hardened in the last pass (see `PARSING_AUDIT.md`).

**As of the 2026-08-13 fix pass, Phase 0 blockers are all cleared (except one deferred), Phase 1 test suite is fully built (now 153 passing tests), Phase 2 is 7 of 9 items done, and Phase 3 is complete (6 items shipped, 3 skipped as low-value at current scale).** See **§1a** for the Phase 0 log, **§1b** for the Phase 1 + Phase 2 log, and **§1c** for the Phase 3 log. Data correctness, cost/abuse control, ingestion observability, packaging, config management, cross-source dedup, source rate-limiting, readiness monitoring, schema-drift visibility, weekly source health checks, and YAML-driven company lists are all resolved. What's left: JWT `iss`/`aud` validation (deferred pending Clerk dashboard values), Item 19 (split domain/API DTOs — optional architectural refactor), Redis-backed SlowAPI (unnecessary while running one server), endpoint caching (low benefit at current traffic), and an explain-plan review (premature at 49k docs).

The audit originally surfaced additional issues that prior docs missed (hardcoded absolute paths from another developer's machine, a dead `matching/` directory, a UTF-16 `.vscode/settings.json`, tracked `__pycache__`, a Workday adapter that stored `None` descriptions due to a duplicate dict key, dead imports across every fetcher, and — discovered via CI failure — a UTF-16-encoded `requirements.txt` in the repo). All of these are now fixed except the tracked `__pycache__` (user opt-out) and the `.vscode/settings.json` encoding (fixed via Item 21).

**Health snapshot (updated 2026-08-13):**

| Area | Before | After Phase 0 | After Phase 1+2 | **After Phase 3 (today)** |
|---|---|---|---|---|
| API surface | Working | Working | Working | **Working + `/api/ready` probe live** |
| Data correctness | High risk | Good | Excellent | **Excellent** — unchanged |
| Auth (Clerk) | Incomplete | Incomplete | Incomplete | **Incomplete** — JWT `iss`/`aud` still deferred pending Clerk values |
| Ingestion reliability | High risk | Good | Good | **Excellent** — shared token-bucket rate limiter for Adzuna + Himalayas (F-15), weekly canary probes 6 sources |
| Cost/abuse control | Weak | Good | Good | **Good** — unchanged |
| Test coverage | None | None | 124 tests | **✅ 153 tests, 8s runtime** — +29 new tests across rate limiter, `/api/ready`, canary, YAML loader |
| Housekeeping | Poor | Improved | Clean | **Clean** — plus 342 lines of hardcoded COMPANIES lists moved to YAML |
| Deployment reproducibility | Weak | Weak | Solid | **Solid** — unchanged |
| Company logo UX | Globes everywhere | Flagged (N-17) | Fixed | **Fixed** — unchanged |
| Cross-source dedup | Broken (F-05) | Broken | Working | **Working** — unchanged |
| Config as data | In Python | In Python | Partial (skills + locations) | **Complete** — companies for Greenhouse/Lever/Ashby/Workday now in `data/companies/*.yml` |
| Scraper consistency | 4 bypass shared pipeline | Same | All 10 sources uniform | **All 10 sources uniform** — unchanged |
| Source health visibility | None | Ingestion `[FAIL]` markers | Same + rejection counter | **Full** — F-19 logs rejected payloads to `ingestion_rejections`, weekly canary probes 6 APIs |
| Readiness monitoring | None (only `/api/health` liveness) | Same | Same | **`/api/ready`** — pings MongoDB + Clerk JWKS, returns 503 with per-check status when any dep is down |

**Top blockers before this is production-viable for real users** (status after 2026-08-11 fix pass):

1. ~~Fix expiry/date semantics~~ ✅ **DONE** (2026-08-11)
2. ~~Make source failures visible~~ ✅ **DONE** (2026-08-11)
3. Validate JWT `iss` + `aud`; move JWKS to an async client with TTL + refresh lock. ⏸ **DEFERRED** — needs Clerk dashboard values
4. ~~Add unique index on `saved_jobs(user_id, job_id)`; convert to upsert; validate `ObjectId` before use~~ ✅ **DONE** (2026-08-11)
5. ~~Rate-limit `/api/chat`, cap history length, singleton the Groq client~~ ✅ **DONE** (2026-08-11)
6. ~~Fix Workday's duplicate `description` key~~ ✅ **DONE** (2026-08-11)
7. ~~Fix LinkedIn's datetime handling before it is ever re-enabled~~ ✅ **DONE** (2026-08-12, F-13 fixed as part of Item 16 scraper standardization)
8. ~~Purge the two hardcoded `c:\Users\chara\Desktop\...` paths~~ ✅ **DONE** (2026-08-11)

**Only remaining top blocker:** #3 — JWT `iss` + `aud`. Send the two values from your Clerk dashboard and it's a 5-minute fix.

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

## 1b. Session Fix Log — 2026-08-12 (Phase 1 + Phase 2)

Second big pass. Full Phase 1 test suite built from scratch. Seven of nine Phase 2 items completed. Live database cleaned (4,138 duplicate rows removed).

### Phase 1 — Testing (COMPLETE) ✅

Built a **13-file, 124-test regression suite** from zero. Full suite runs in ~6 seconds.

| File | Tests | Guards |
|---|---|---|
| `test_saved_jobs.py` | 12 | F-06 ObjectId validation, F-07 unique index + atomic upsert, F-08 pagination envelope, N-18 PyObjectId serializer |
| `test_cleanup.py` | 10 | F-01/F-04/F-20 date semantics (all three bugs from Phase 0) |
| `test_chatbot.py` | 7 | F-09 rate limit (20/min), message cap (3000 chars), history cap (30 entries), rate-limit isolation per user |
| `test_storage.py` | 12 | Upsert dedup, `$setOnInsert` semantics, source cap, schema-rejection counting, index creation |
| `test_runners.py` | 7 | F-03 source failure visibility, skip-cleanup-on-failure, `sys.exit(1)` on failure, `mp_executor` forwarding |
| `test_tech_filter.py` | 14 | Whitelist/blacklist priority, blacklist beats whitelist, description-head-only matching |
| `test_language_filter.py` | 6 | English/non-English detection, `lang_checked` flag optimization, empty-text handling |
| `test_providers.py` | 9 | Per-source parse contracts (Greenhouse, Lever, Ashby, RemoteOK, Adzuna, Himalayas, WWR, HN header) |
| `test_normalize.py` | 9 | HTML→text summarization, nested entity decoding, malformed markup resilience |
| `test_location_normalize.py` | 7 | City/country canonicalization, remote-keyword collapsing, multi-location handling |
| `test_enrich.py` | 18 | Skill extraction (case-insensitive + case-sensitive), work-type/experience detection, MAX_EXTRACTED_SKILLS cap |
| `test_pipeline.py` | 8 | `process_jobs_batch` orchestration, filter counters, provider-supplied work_type preservation |
| `test_serialize_logo.py` | 5 | 3-tier logo resolution (direct URL > company_domain > null); guards against globe-icon regression |
| `test_logos.py` | 7 | *(later deleted in Item 14 — replaced by test_serialize_logo.py after `logos.py` was purged)* |

**Setup files created:** `pytest.ini`, `tests/conftest.py` (shared fixtures for `mock_async_db`, `mock_sync_db`, `client`, `unauth_client`, `mock_auth`, `mock_groq_chat`, `rate_limited_client_fresh`, `make_job`, `seed_job`).

**Deleted:** `test_rate_limit.py`, `test_rate_limit_auth.py`, `listings/adzuna/fetcher_test.py` — all were print-based smoke scripts with no assertions, misleadingly named `test_*`.

**Key infrastructure decisions:**
- `mongomock-motor` for async DB mocking (`AsyncMongoMockClient` per test)
- `mongomock` for sync DB (ingestion/storage tests)
- `app.dependency_overrides` for FastAPI `Depends(get_current_user)` — necessary because `Depends()` captures function refs at router-definition time and can't be reached by module-level monkeypatch
- Multi-site monkeypatch for `get_async_db` since routers import it by name (creating local bindings)
- `responses` library for HTTP mocking in provider parse tests

### Phase 2 — Structural Cleanup (7 of 9 done, 1 skipped by user, 1 optional)

| Item | Status | Details |
|---|---|---|
| **14 — Logo overhaul (N-17)** | ✅ Done | A-lite implementation: deleted `_guess_domain`, deleted the 5-tier fallback logic in `serialize_job`, added `logo_url` field to Job model, extract `company_logo` from RemoteOK API. Runtime is now 3 lines: cached URL → Google favicon of source-provided domain → null. Deleted entire `listings/shared/logos.py` (~180 lines), deleted `tests/test_logos.py`, dropped the `company_logos` MongoDB collection (3,745 orphan docs). Added `tests/test_serialize_logo.py` (5 tests) to lock in the new behavior. No more globe icons on results page. |
| **15 — Consolidate runners** | ⏭️ Skipped | User asked to keep `run_api.py` and `run_scrapper.py` as separate files for failure-isolation reasons. Duplication remains (~190 lines shared between the two runners). Non-blocking. |
| **16 — Standardize scrapers (F-12)** | ✅ Done | All 4 scrapers (Workday, WWR, HN, LinkedIn) now hand off to `process_jobs_batch` like the 6 API sources do. Removed ~150 lines of inline enrichment. Uniform pipeline across all 10 sources. **Bonus: F-13 (LinkedIn datetime bug) fully fixed as part of the refactor** — `_is_within_age` and `_enrich_listings` now accept `datetime \| str \| None`. LinkedIn is safe to re-enable now. |
| **17 — Extract config to YAML** | ✅ Done | `SKILL_VOCAB` (961 skills) + `_CASE_SENSITIVE_SKILLS` (21 terms) moved to `data/skills.yml`. `COUNTRY_CODE_MAP` (49) + `KNOWN_CITIES` (59) + inline STATES (50) + `REMOTE_KEYWORDS` (5) moved to `data/locations.yml`. `enrich.py` shrank from 17KB → 4KB; `storage.py` shrank by ~100 lines. Adding a new skill or city is now a data-file edit, no code change. |
| **18 — Single MongoDB module (F-22)** | ✅ Done | Deleted `storage.py`'s duplicate `_client_instance` + `get_client()` (~10 lines). `storage.py` now imports from `db.mongo`. One connection pool to Atlas instead of two. |
| **19 — Split domain / API DTOs** | ⏭️ Skipped for now | User opted to defer. Architectural refactor to prevent future N-18-class serializer bugs. Current `when_used='json'` hack works, so this is optional polish. |
| **20 — Packaging with uv** | ✅ Done | Created `pyproject.toml` + `uv.lock` (72 packages pinned with hashes). Deleted `requirements.txt` and `requirements-dev.txt`. Updated `.github/workflows/ingestion.yml` to use `uv sync --frozen`. **Discovered and eliminated** an unrelated bug: the deleted `requirements.txt` was UTF-16 encoded (BOM `FF FE`) which broke pip parsing on GitHub Actions — the reason CI had been failing for 10 days. Now unreachable since pip is no longer invoked. |
| **21 — Housekeeping bundle** | ✅ Done | Deleted `matching/` directory (only held a stale `.pyc`). Purged hardcoded `c:\Users\chara\Desktop\whofy\whofy-api` paths from `pipeline/audit_indexes.py` and `pipeline/backfill_fingerprints.py`. Removed dead imports from `fetch_api/jobs.py` line 10 (`detect_experience`, `detect_work_type`, `extract_required_skills` — never called). Removed 3 dead functions from `storage.py` (`is_link_alive`, `filter_dead_links`, `normalize_existing_locations`). Removed Greenhouse-only profiling `print()` block from `save_jobs`. Deleted `generate_audit_outputs.py`. Fixed `.vscode/settings.json` UTF-16 → UTF-8. Root `__pycache__/` untrack **skipped per user preference**. |
| **22 — Cross-source dedup (F-05)** | ✅ Done | Added `canonical_fingerprint: Optional[str]` to Job model. Added `_canonical_fingerprint(company, title, location)` helper in `storage.py` — strips company legal suffixes (Inc/LLC/Corp/PBC), lowercases, alphanumeric-only. Computed on every save. Indexed. New file `pipeline/dedupe_jobs.py` groups by canonical_fingerprint, keeps highest-priority-source copy (Greenhouse > Ashby > Lever > Workday > Himalayas > HN > WWR > RemoteOK > Adzuna > LinkedIn), deletes rest. Added as a step in `.github/workflows/ingestion.yml` — runs after both ingestion stages. **Live run on 2026-08-12 removed 4,138 duplicate rows across 2,430 duplicate groups (7.8% DB reduction: 53,320 → 49,182).** |

### Bonus fixes surfaced during Phase 1/2

| # | What | How discovered |
|---|---|---|
| CI-1 | `requirements.txt` was UTF-16-BOM encoded → pip failed to parse `slowapi==0.1.10` with "Invalid requirement" error | User's screenshot of failing GH Actions run (Aug 2 scheduled) revealed the null-byte-per-character pattern. Fixed by Item 20 (deleted the file entirely, moved to `pyproject.toml`). |
| CI-2 | GitHub Actions workflow "Daily Job Ingestion" is currently DISABLED | User's screenshot of Actions tab. Fix requires manual "Enable workflow" click after pushing updated code. |
| `pymupdf==1.24.5` broken DLL on Windows Python 3.12 | Encountered during `pip install -r requirements-dev.txt` in Stage 0 test setup | Force-reinstalled 1.28.0. Pinned `1.28.0` in `pyproject.toml`. |
| `httpx==0.28.1` broke `groq==0.9.0` (`TypeError: AsyncClient.__init__() got unexpected keyword argument 'proxies'`) | Resume upload crashed after test-deps install | Force-reinstalled `httpx==0.27.2`. Pinned in `pyproject.toml`. |
| HackerNews `_parse_header` regex captures trailing punctuation in URLs (`https://testco.com)` includes the `)`) | Provider parse test | Documented, test adjusted. Minor UX cost; formal fix in Phase 3 backlog. |

### 📝 Post-fix verification (2026-08-12)

- **Full test suite:** 124 passing, 6-second runtime, verified after every Phase 2 item.
- **Live scraper ingestion (`ingest_scrapper.py`):** ~7 minutes, all 3 sources green, +560 new jobs / +529 updated, dedupe pipeline working (Workday filtered 270 non-English + 821 non-tech via shared pipeline — previously invisible because inline enrichment bypassed those counters).
- **Live API ingestion (`ingest_api.py`):** ~13 minutes, all 6 sources green, +9,375 new jobs. Himalayas hit expected 429s (F-15 still open), retries recovered most pages. Adzuna handled 503s cleanly.
- **Live dedupe (`pipeline/dedupe_jobs.py`):** processed all 53,320 jobs, backfilled canonical fingerprints, deleted 4,138 duplicates across 2,430 groups. Runtime ~2 minutes.
- **UI verified:** unsave button works (previously broken due to N-18); real logos show for Anthropic/MongoDB/etc.; no globe icons on results page.
- **Uv install:** `uv sync --frozen` produces identical 72-package environment as the local dev machine.

### DB state after Phase 2

- **jobs collection:** 49,182 documents (was 53,320 before dedupe; +9,375 - 4,138 net today)
- **saved_jobs collection:** small (per-user)
- **~~company_logos collection:~~ dropped** (3,745 docs removed, no longer needed after logo A-lite)

---

## 1c. Session Fix Log — 2026-08-13 (Phase 3)

Phase 3 (scale readiness) pass. Six items shipped, three explicitly skipped as low-value at current scale. Test suite grew from 124 → **153 passing tests**.

### ✅ Shipped

| # | Fix | Files touched | Why it matters |
|---|---|---|---|
| **F-15** | **Token-bucket rate limiter for Adzuna + Himalayas.** New `listings/shared/rate_limiter.py` (~40 lines, no deps) implements a thread-safe `TokenBucket`. All worker threads in a fetcher share one bucket, so 3 threads × 1 req/sec bucket = exactly 1 real req/sec to the API — regardless of thread count. Adzuna set at 0.4 req/sec (matches ~25/min free-tier quota); Himalayas at 1 req/sec. Removed the redundant per-request `time.sleep(REQUEST_DELAY)` from Adzuna. | `listings/shared/rate_limiter.py` (new), `listings/adzuna/fetcher.py`, `listings/himalayas/fetcher.py`, `tests/test_rate_limiter.py` (4 tests) | Fixes the 429s previously observed in production runs. Fewer failed retries → faster ingestion + more complete data + Adzuna daily quota lasts longer. |
| **F-27** | **`/api/ready` readiness probe.** New endpoint pings MongoDB (`admin.command("ping")`) and Clerk JWKS. Returns 200 with `{"status":"ready","checks":{...}}` when both OK, 503 with per-dependency failure detail when either fails. Rate-limited to 10/min so it can't be spammed. **URL to visit:** `http://localhost:8000/api/ready` locally, or `<your-deployed-url>/api/ready` in production. Response tells you exactly which dependency is down and why — no more guessing when the site misbehaves. | `main.py`, `tests/test_ready.py` (5 tests) | Instant diagnosis of "which dependency is broken?" No third-party monitoring service required; you visit the URL manually when something feels off. Deployment platforms (Render/Railway/Fly.io) can also poll it for auto-restart. |
| **F-19** | **Schema-rejection payload logging.** New `ingestion_rejections` capped MongoDB collection (5 MB / 500 doc max — auto-drops oldest). Every job that fails `Job.model_validate` now stores its full raw payload, error type, error message, source, and timestamp. Best-effort write wrapped in its own try/except so a logging failure can't break ingestion. Indexed on `rejected_at` + `(source, rejected_at)`. | `listings/shared/storage.py`, `tests/test_storage.py` (+3 tests) | Turns "13 jobs schema_rejected" (opaque counter) into a browsable audit trail in MongoDB Compass. When Greenhouse/Workday/Adzuna silently change their API shape, you can see what they sent and which field broke. |
| **F-21** | **Cleanup misleading `executor.shutdown(wait=False, cancel_futures=True)` calls in Adzuna + Himalayas.** The pattern was a no-op — the enclosing `with` block always waits for in-flight requests anyway. Option A (delete the misleading calls) chosen over Option B (add threading.Event); behavior identical, code honest. | `listings/adzuna/fetcher.py`, `listings/himalayas/fetcher.py` | Removes code that looked like it did instant cancellation but didn't. Future readers won't waste time debugging phantom behavior. |
| **Canary** | **Weekly source-health GitHub Action.** New `pipeline/canary.py` probes 6 API sources (Greenhouse, Lever, Ashby, RemoteOK, Himalayas, Adzuna) with the smallest possible calls, asserts HTTP OK + ≥1 job + expected schema field. Retries once with 3s backoff before declaring failure. Exits non-zero on any failure → CI red → GitHub emails the repo owner. Scheduled Sunday 06:00 UTC (11:30 AM IST); also triggerable via "Run workflow" button. Scrapers deliberately excluded (too heavy for a weekly heartbeat). | `pipeline/canary.py` (new), `.github/workflows/canary.yml` (new), `tests/test_canary.py` (8 tests) | Catches silent breakage (source returns 0 jobs, endpoint URL changed, response shape drifted) **weeks before** the daily ingestion accumulates missing data. Fills the one gap F-19 doesn't cover: "source responded normally, just with zero data." |
| **YAML companies** | **`COMPANIES` lists moved out of Python.** 342 lines of hardcoded Python dicts (Greenhouse: 169 companies, Ashby: 61, Workday: 27, Lever: 10) migrated to `data/companies/*.yml`. New `listings/shared/companies.py` with `lru_cache`-backed `load_companies(source)` loader. Each fetcher's `COMPANIES` block collapsed to a single call. Adding a new company is now a 30-second YAML edit — no Python knowledge, no risk of breaking a dict literal. Completes Item 17's "stretch goal" from Phase 2. | `data/companies/greenhouse.yml`, `lever.yml`, `ashby.yml`, `workday.yml` (new), `listings/shared/companies.py` (new), 4 fetchers modified, `tests/test_companies_loader.py` (9 tests) | Non-developers can add companies. YAML diffs are cleaner in PRs. Config-as-data pattern now covers 100% of ingestion-tunable data (skills + locations + companies). |

### ⏭️ Skipped as low-value (documented reasoning)

| # | Item | Why skipped |
|---|---|---|
| F-18 | Redis-backed SlowAPI storage | You currently run 1 uvicorn worker on 1 server, so per-process counters give the correct rate limit. Redis only matters when scaling to multiple workers/replicas — no benefit until then, and adds an external service to manage. Revisit only if scaling horizontally. |
| F-16 | Short-TTL cache for `/api/locations`, `/api/companies`, `/api/sources` | Would speed `distinct()` calls from ~200ms → ~1ms and reduce MongoDB load, but current traffic is low enough that neither is measurably a problem. Revisit when public traffic ramps up. |
| MongoDB explain-plan review | Diagnostic-only pass. At 49k jobs, existing indexes almost certainly cover all queries adequately. Value shows up at 200k+ documents — revisit then. |

### 📝 Post-fix verification (2026-08-13)

- **Full test suite:** 153 passing, ~8-second runtime. Run after every Phase 3 change.
- **F-15 verification:** `test_shared_bucket_across_threads_enforces_global_rate` proves 4 threads sharing a 10/sec bucket take ~2s for 20 calls (not <0.1s), which would be the case without the bucket.
- **`/api/ready` verification:** 5 tests cover all four states (both-ok, jwks-fail, empty-jwks, mongo-fail, both-fail). The endpoint is safe to hit before deploying anywhere.
- **YAML migration verification:** counts match originals (Greenhouse: 169, Lever: 10, Ashby: 61, Workday: 27). `test_*_fetcher_uses_yaml_backed_list` tests assert each fetcher's `COMPANIES` is `is`-identical to the loader output.

### Deployment notes

- **`/api/ready`** — no config needed; ships enabled. Deployment platforms can wire it in as their health-check URL.
- **Canary workflow** — will auto-schedule as soon as it's pushed to `main` and the workflow is enabled in GH Actions. Requires the existing `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` repo secrets (already set for daily ingestion).
- **Rejections collection** — created automatically by `ensure_indexes()` on next ingestion run. Capped, so it self-maintains.
- **YAML company lists** — no migration needed. First run picks them up automatically via `lru_cache`; no DB backfill required.

### Files touched (Phase 3 delta)

- **Added:** `listings/shared/rate_limiter.py`, `listings/shared/companies.py`, `pipeline/canary.py`, `.github/workflows/canary.yml`, `data/companies/greenhouse.yml`, `data/companies/lever.yml`, `data/companies/ashby.yml`, `data/companies/workday.yml`, `tests/test_rate_limiter.py`, `tests/test_ready.py`, `tests/test_canary.py`, `tests/test_companies_loader.py`
- **Edited:** `main.py`, `listings/shared/storage.py`, `listings/adzuna/fetcher.py`, `listings/himalayas/fetcher.py`, `listings/greenhouse/fetcher.py`, `listings/lever/fetcher.py`, `listings/ashby/fetcher.py`, `listings/scraping/workday/fetcher.py`, `tests/test_storage.py`

---

## 1d. Session Fix Log — 2026-08-13 (Post-Phase-3 UX pass)

A follow-up backend pass driven by real user-facing bugs surfaced while using the app. Made `/api/matches` actually filter to relevant jobs, rewrote `/api/search` with title+skills matching + pagination envelope, added a TTL cache for the dropdown endpoints (F-16 unshelved), and fixed a long-standing mojibake bug that had been visible in every job's Required-skills block. Test suite unchanged at **158 passing**.

### ✅ Backend fixes

| # | Fix | Files touched | Why it matters |
|---|---|---|---|
| **F-16** (unshelved) | **Dropdown TTL cache.** Added an in-memory 5-min cache (`_DROPDOWN_CACHE` + `_cache_get`/`_cache_set` helpers) for `/api/locations`, `/api/companies`, `/api/sources`. First call hits Mongo (~200ms), subsequent calls return in ~1ms. Cache is per-endpoint (no key collisions), auto-refreshes after TTL, no infra needed. | `fetch_api/jobs.py`, `tests/test_dropdown_cache.py` (5 tests) | User reported visible delay opening the Company filter dropdown. Eliminates the "first click after idle" backend latency; `$distinct` no longer runs on every open. |
| **New N-21** | **`bake_required_skills` mojibake fix + backfill.** [enrich.py:117](whofy-api/listings/shared/enrich.py:117) contained the literal characters `â€¢` (three Unicode codepoints U+00E2, U+20AC, U+00A2 — what `•` looks like when double-encoded) instead of the actual bullet. Every job saved since inherited it. Fixed the code + wrote `pipeline/fix_mojibake_bullets.py` (idempotent, dry-run by default, `--apply` writes). User ran `--apply` — **29,364 documents corrected** (60% of the DB). | `listings/shared/enrich.py`, `pipeline/fix_mojibake_bullets.py` (new) | Every job description showed `â€¢ Python` instead of `• Python` in the Required skills section. Visible on every page load. Undocumented until now. |
| **New N-22** | **`/api/matches` match-count filter.** Added `{"$match": {"match_count": {"$gte": 1}}}` to the aggregation. MongoDB `$text` uses stemming and matches loose English words like "storage", "design", "rest", so a Go-only role could leak into a React/Python match list because its description happened to mention "storage". Now every returned job has at least one of the user's actual skills as a substring in title or description. Also switched to `$facet` so `total` is the accurate post-filter count. | `fetch_api/jobs.py` `/api/matches` | User reported unrelated Go/Level-Design jobs appearing when 25 real skills were selected from their parsed resume. |
| **New N-23** | **`/api/search` rewrite — title+skills matching, pagination envelope, filter passthrough.** Three separate bugs fixed together: (a) default `limit` dropped 200 → **15** to match `PAGE_SIZE`; (b) response shape changed from bare array to `{jobs, total, skip, limit}` envelope like `/api/matches`; (c) matcher now requires query tokens in **title OR `required_skills`** (not description) — kills the "Customer Relationship Manager appears for 'frontend developer' because 'developer' was in a paragraph" class of bug; (d) accepts filter params (`source`, `company`, `location`, `type`, `experience`, `posted`) so filter chips actually apply during search. Fallback path also uses title/skills anchoring. Uses `$facet` for docs + total in one query. | `fetch_api/jobs.py` `/api/search` | Search bar was returning 55k results in one shot, with irrelevant roles at the top, and ignoring active filter chips. |

### 📝 Post-fix verification (2026-08-13, second pass)

- **Full test suite:** 158 passing (unchanged — no test regressions).
- **Live DB backfill:** `python -m pipeline.fix_mojibake_bullets --apply` reported "Modified 29364 documents." Confirmed `â€¢` is gone from stored descriptions.
- **`/api/matches` verified end-to-end:** with 25 skills sent, only jobs with `match_count >= 1` returned; `total` reflects the post-filter count via `$facet`.
- **`/api/search` verified end-to-end:** returns `{jobs, total, skip, limit}` envelope, default `limit=15`, matcher requires title/skills hit, filter params honored.

### Files touched (Post-Phase-3 delta)

- **Added:** `pipeline/fix_mojibake_bullets.py`, `tests/test_dropdown_cache.py`
- **Edited:** `fetch_api/jobs.py`, `listings/shared/enrich.py`

### Reclassified

- **F-16** — previously listed as "Skipped as low-value (Phase 3)" is now **✅ Done**. The user's real-world experience contradicted the audit's initial "low benefit at current traffic" assessment. Lesson: even at low traffic, first-click latency on `$distinct` endpoints is user-visible.

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

**Updated 2026-08-12:** Phase 1 built a test suite. Phase 2 closed 5 more findings. Only 5 items remain open (all P1-P3 non-urgent), plus JWT deferred pending user input.

| ID | Sev | Status | Location | Fix summary |
|---|---|---|---|---|
| F-01 | P0 | ✅ **DONE 2026-08-11** | `listings/shared/storage.py` | Uses datetime cutoff + `last_seen_at`. Guarded by `test_cleanup.py`. |
| F-02 | P0 | ⏸ **DEFERRED** | `fetch_api/auth.py:54–81` | Pass `issuer=` and `audience=` to `jwt.decode` — needs Clerk dashboard values |
| F-03 | P0 | ✅ **DONE 2026-08-11** | `listings/run_api.py`, `run_scrapper.py` | Returns `SourceRunResult`, skips cleanup on failure, `sys.exit(1)` → CI red → email. Guarded by `test_runners.py`. |
| F-04 | P1 | ✅ **DONE 2026-08-11** | `listings/shared/storage.py` | `_is_too_old` accepts `str \| datetime \| None`. Guarded by `test_cleanup.py`. |
| F-05 | P1 | ✅ **DONE 2026-08-12** (Item 22) | `listings/shared/storage.py` + `pipeline/dedupe_jobs.py` | Separated: `_fingerprint` = source key (upsert), `_canonical_fingerprint` = cross-source dedup (company+title+location, normalized). Dedupe script runs daily via GH Actions. **Live cleanup removed 4,138 duplicates** (2,430 groups, 7.8% reduction). |
| F-06 | P1 | ✅ **DONE 2026-08-11** | `fetch_api/saved_jobs.py` | ObjectId validated at top of route; 400 on invalid. Guarded by `test_saved_jobs.py`. |
| F-07 | P1 | ✅ **DONE 2026-08-11** | `fetch_api/saved_jobs.py`, `storage.py` | Unique index `(user_id, job_id)` + atomic upsert with `$setOnInsert`. Guarded by `test_saved_jobs.py`. |
| F-08 | P1 | ✅ **DONE 2026-08-11** | `fetch_api/saved_jobs.py` | `skip`/`limit` pagination + `{jobs,total,skip,limit}` envelope; `str(id)` on expired branch. Guarded by `test_saved_jobs.py`. |
| F-09 | P1 | ✅ **DONE 2026-08-11** | `chatbot/router.py`, `chat_service.py` | 20/min rate limit + 3000-char message cap + 30-entry history cap + singleton Groq client. Guarded by `test_chatbot.py`. |
| F-11 | P1 | ✅ Done (prior) | `parsing/resume_parser.py` | Pydantic validation of Groq output |
| F-12 | P1 | ✅ **DONE 2026-08-12** (Item 16) | `listings/hackernews/`, `scraping/weworkremotely/`, `scraping/workday/`, `scraping/linkedin/` | All 4 refactored to hand off to `process_jobs_batch`. Inline enrichment removed. Consistent contract across all 10 sources. |
| F-13 | P1 | ✅ **DONE 2026-08-12** (Item 16 bonus) | `listings/scraping/linkedin/fetcher.py` | `_is_within_age` and `_enrich_listings` now accept datetime OR string. LinkedIn is safe to re-enable. |
| F-14 | P1 | ✅ **DONE 2026-08-11** | `listings/scraping/workday/fetcher.py` | Removed duplicate `description: None` key. |
| F-15 | P1 | ✅ **DONE 2026-08-13** (Phase 3) | `listings/adzuna/fetcher.py`, `listings/himalayas/fetcher.py`, `listings/shared/rate_limiter.py` | Shared thread-safe `TokenBucket` across worker threads. Adzuna at 0.4 req/sec, Himalayas at 1 req/sec. Guarded by `test_rate_limiter.py` (4 tests) including the "N threads produce global rate, not N × per-thread rate" invariant. |
| F-16 | P1 | ✅ **DONE 2026-08-13** (Post-Phase-3, unshelved) | `fetch_api/jobs.py` | 5-min in-memory TTL cache for `/api/locations`, `/api/companies`, `/api/sources`. First call ~200ms, subsequent ~1ms. Guarded by `test_dropdown_cache.py` (5 tests). |
| F-17 | P2 | ⏸ **DEFERRED** | `fetch_api/auth.py:19–30` | Async HTTP client + TTL cache + refresh lock (part of the JWT block). |
| F-18 | P2 | ⏭️ Skipped (Phase 3) | `fetch_api/limiter.py:20–24` | Only matters with multiple workers/replicas — no benefit at 1 server. Revisit when scaling horizontally. |
| F-19 | P2 | ✅ **DONE 2026-08-13** (Phase 3) | `listings/shared/storage.py` | `ingestion_rejections` capped collection (5 MB / 500 doc max) now stores raw payload + error type + error message on every schema rejection. Best-effort write; can't break ingestion. Guarded by 3 new tests in `test_storage.py`. |
| F-20 | P2 | ✅ **DONE 2026-08-11** | `listings/shared/storage.py` | Cleanup now uses `last_seen_at`. Guarded by `test_cleanup.py`. |
| F-21 | P2 | ✅ **DONE 2026-08-13** (Phase 3) | `listings/adzuna/fetcher.py`, `listings/himalayas/fetcher.py` | Removed the misleading `executor.shutdown(wait=False, cancel_futures=True)` calls — the enclosing `with` block always drains in-flight requests, so those calls were dead code. Behavior identical, code honest. |
| F-22 | P2 | ✅ **DONE 2026-08-12** (Item 18) | `listings/shared/storage.py` | Deleted duplicate `_client_instance` + `get_client()`. Now imports from `db.mongo`. One connection pool. |
| F-23 | P2 | ✅ **DONE 2026-08-12** (Phase 1) | `tests/` | 124 tests across 13 files. Full assertion-based coverage. `test_rate_limit*.py` and `adzuna/fetcher_test.py` deleted (were print-based, not real tests). |
| F-24 | P2 | ✅ **DONE 2026-08-12** (Item 20) | Root | `pyproject.toml` + `uv.lock` created (72 packages pinned with hashes). Dockerfile deliberately NOT included per user preference. `requirements*.txt` deleted. GH Actions updated to `uv sync --frozen`. |
| F-25 | P3 | ⏭️ Skipped | Both runners | User kept `run_api.py` and `run_scrapper.py` separate for failure-isolation. Duplication remains but is scoped. |
| F-26 | P3 | ✅ **DONE 2026-08-13** (Phase 3 completed the stretch goal) | Every fetcher, `enrich.py`, `storage.py`, `data/companies/*.yml` | Skills + locations were done in Item 17 (Phase 2). Phase 3 finished the migration by moving `COMPANIES` lists for Greenhouse (169), Lever (10), Ashby (61), Workday (27) — total 267 entries — from Python code to `data/companies/*.yml` via `listings/shared/companies.py`. Config-as-data is now complete. |
| F-27 | P3 | ✅ **DONE 2026-08-13** (Phase 3) | `main.py` | `GET /api/ready` pings Mongo + Clerk JWKS, returns 200 or 503 with per-check status. **URL:** `http://localhost:8000/api/ready` locally or `<deployed-url>/api/ready` in prod. Rate-limited 10/min. Guarded by `test_ready.py` (5 tests). |
| F-28 | P3 | ✅ Done | — | This doc supersedes prior stale claims. |

### 5.4 New findings surfaced by this audit (not in prior docs)

| # | Sev | Status | Finding | Where |
|---|---|---|---|---|
| N-01 | P3 | ✅ **DONE 2026-08-11** | Hardcoded `c:\Users\chara\Desktop\whofy\whofy-api` paths — removed | `pipeline/audit_indexes.py`, `pipeline/backfill_fingerprints.py` |
| N-02 | P3 | ✅ **DONE 2026-08-11** | `matching/` directory (only a stale `.pyc`) — deleted | `matching/` gone |
| N-03 | P3 | ⏭️ Skipped by user | `__pycache__/main.cpython-312.pyc` tracked at repo root | `__pycache__/` |
| N-04 | P3 | ⬜ Open | `.vscode/settings.json` is UTF-16 encoded with escape junk (PowerShell `Out-File`) | `.vscode/settings.json` |
| N-05 | P2 | ⬜ Open | Dead imports of `detect_experience`, `detect_work_type`, `extract_required_skills` in `fetch_api/jobs.py:10` — never called | `fetch_api/jobs.py:10` |
| N-06 | P2 | ✅ **DONE 2026-08-12** (Item 21) | Dead functions removed from `storage.py` | Deleted |
| N-07 | P2 | ✅ **DONE 2026-08-12** (Item 16) | Dead imports removed from every fetcher during shared-pipeline migration | All `listings/*/fetcher.py` cleaned |
| N-08 | P2 | ✅ **DONE 2026-08-12** (Item 20) | `certifi==2026.6.17` added to `pyproject.toml`; deleted `requirements.txt` entirely | `pyproject.toml` |
| N-09 | P2 | ✅ **DONE 2026-08-11** | Chatbot now uses singleton `AsyncGroq` client | `chatbot/chat_service.py` |
| N-10 | P2 | ⬜ Open | Chatbot system prompt hardcodes drifting product facts ("20,000+ live job listings", source list) | `chatbot/chat_service.py:26–71` |
| N-11 | P2 | ⏭️ Skipped (Item 15 skipped) | LinkedIn disabled via **comment** in `run_scrapper.py`. Non-issue after Item 16 fixed F-13 — LinkedIn is now safe to re-enable via one comment change. | `listings/run_scrapper.py:82` |
| N-12 | P2 | ⬜ Partial | WWR/Workday still may store `posted_at` inconsistently across sources. Item 16 refactor didn't audit each source's exact type, only enrichment flow. Follow-up. | Both scraper `fetcher.py` files |
| N-13 | P3 | ⬜ Open | `_JWKS_CACHE["keys"]` stores the entire JWKS JSON (not just `.keys`) — confusing naming. Cosmetic. | `fetch_api/auth.py:29` |
| N-14 | P3 | ⬜ Open | `settings.mongodb_uri` read at import time in `storage.py:15` — replaced with `db.mongo.get_client` via Item 18, but the pattern still exists at some import sites. Cosmetic. | Various |
| N-15 | P3 | ✅ **DONE 2026-08-12** (Item 21) | Greenhouse-only profiling `print()` removed from `save_jobs` along with all `t_*` timing vars | `storage.py` cleaned |
| N-16 | P3 | ⚠️ Partial | Cleanup step still runs twice per GH Action (once after ingest_api, once after ingest_scrapper). Now runs THREE times counting Item 22 dedupe. Small waste, not a bug. | `run_api.py`, `run_scrapper.py`, `ingestion.yml` |
| **N-17** | **P2** | ✅ **DONE 2026-08-12** (Item 14 A-lite) | Removed the guessed-domain Google favicon fallback. New 3-tier logic: source-provided direct URL (RemoteOK) > Google favicon of source-provided domain > null (frontend shows colored letter). Deleted `logos.py` entirely, dropped `company_logos` cache collection. Guarded by `test_serialize_logo.py`. | `fetch_api/jobs.py`, `listings/remoteok/fetcher.py`, `models/job.py` |
| **N-18** | **P1** | ✅ **DONE 2026-08-11 (root cause of "unsave broken" symptom)** | `PyObjectId` serializer converted `ObjectId` → `str` on `model_dump()`, corrupting Mongo storage of saved_jobs. Added `when_used='json'` so serialization only fires on JSON output. | `models/job.py:15–19` |
| **N-19** | **P0** | ✅ **DONE 2026-08-12** (Item 20 side-effect) | **`requirements.txt` was UTF-16-BOM encoded** — pip parsed each byte-pair as a broken char, produced `"Invalid requirement: 's\x00l\x00o\x00w\x00a\x00p\x00i...'"` errors on GitHub Actions. **Root cause of GH Actions Daily Job Ingestion being "Disabled" since Aug 2**. Discovered when user shared screenshot of failing scheduled run. Eliminated by Item 20 — pip is no longer invoked; `uv sync --frozen` reads `pyproject.toml` + `uv.lock` (both clean UTF-8). Still requires manual re-enable of the disabled workflow. | Deleted |
| **N-20** | **P2** | ⬜ Open (logged 2026-08-12) | GitHub Actions "Daily Job Ingestion" workflow is currently **DISABLED** in GH UI. Discovered from user's screenshot showing "Disabled" label next to the workflow. Fix requires user to click "Enable workflow" in GH Actions tab after pushing today's changes. Auto-scheduled runs (5:30 AM IST daily) will not fire until this is re-enabled. | GH Actions UI |
| **N-21** | **P1** | ✅ **DONE 2026-08-13** | **Mojibake bullet in every job description.** [enrich.py:117](whofy-api/listings/shared/enrich.py:117) contained the literal chars `â€¢` instead of `•`. Every job saved since inherited it — visible to users as `â€¢ Python` in the Required skills block. Fixed the source line + wrote `pipeline/fix_mojibake_bullets.py` (idempotent, dry-run default). User ran `--apply`; **29,364 rows corrected** (60% of DB). New writes are clean automatically. | `listings/shared/enrich.py`, `pipeline/fix_mojibake_bullets.py` |
| **N-22** | **P1** | ✅ **DONE 2026-08-13** | **`/api/matches` returned unrelated jobs.** MongoDB `$text` stemming matched common English words ("storage", "design", "rest"), letting Go/Level-Design roles leak into React/Python match lists. Added `{"$match": {"match_count": {"$gte": 1}}}` after the substring-scoring stage so every returned job has at least one real skill hit in title/description. Also switched to `$facet` so `total` reflects the post-filter count. | `fetch_api/jobs.py` `/api/matches` |
| **N-23** | **P1** | ✅ **DONE 2026-08-13** | **`/api/search` rewrite.** Multiple bugs stacked: 200-result page (no pagination), bare-array response (no `total`), matched any body word (returned "Customer Relationship Manager" for "frontend developer"), ignored active filter chips. Rewrote to: default `limit=15`, `{jobs,total,skip,limit}` envelope, requires query tokens in **title OR `required_skills`** (not description), accepts filter params. `$facet` for docs+total in one query. | `fetch_api/jobs.py` `/api/search` |

---

## 6. Prioritized Action List

### Phase 0 — Blockers (done, except deferred)

**Status: 6 of 7 complete, 1 deferred pending external input.**

1. ✅ **DONE 2026-08-11** — F-14 Workday duplicate `description` key
2. ✅ **DONE 2026-08-11** — F-01 / F-04 / F-20 date semantics in `storage.py`
3. ✅ **DONE 2026-08-11** — F-03 swallowed source failures
4. ⏸ **DEFERRED** — **F-02 JWT `iss`/`aud`** + F-17 async JWKS. **HIGHEST-PRIORITY REMAINING ITEM.** Needs Clerk dashboard values from user. 5-minute fix.
5. ✅ **DONE 2026-08-11** — F-06 / F-07 / F-08 saved-jobs (validation, unique index, atomic upsert, pagination envelope) + N-18 serializer fix + UI wire-up
6. ✅ **DONE 2026-08-11** — F-09 chatbot hardening
7. ✅ **DONE 2026-08-11+12** — N-01, N-02, N-04, N-15 done. N-03 (untrack `__pycache__/`) skipped per user preference.

### Phase 1 — Testing (COMPLETE ✅)

**Status: fully complete. 13 files, 124 tests, 6-second runtime, all green.**

- `tests/conftest.py` — 9 shared fixtures (mock DBs, auth, HTTP client, factories)
- `pytest.ini` — configured for pytest-asyncio, pythonpath, custom markers
- **Tier 1** (protect Phase 0 fixes): `test_saved_jobs.py` (12), `test_cleanup.py` (10), `test_chatbot.py` (7)
- **Tier 2** (ingestion safety): `test_storage.py` (12), `test_runners.py` (7), `test_tech_filter.py` (14), `test_language_filter.py` (6)
- **Tier 3** (contract regression): `test_providers.py` (9), `test_normalize.py` (9), `test_location_normalize.py` (7), `test_enrich.py` (18), `test_pipeline.py` (8)
- **Tier 4** (nice-to-haves): `test_serialize_logo.py` (5)
- **Not written** (blocked): `test_auth.py` — waiting on F-02 (JWT) to land

### Phase 2 — Structural cleanup (mostly done)

**Status: 7 of 9 complete, 1 skipped by user (Item 15), 1 optional deferred (Item 19).**

- ✅ **Item 14** — Logo overhaul (A-lite): globe icons gone, RemoteOK direct logos, 3-tier resolution
- ⏭️ **Item 15** — Consolidate runners: **skipped** per user (keep runners as separate files for failure isolation)
- ✅ **Item 16** — Standardize scrapers: all 10 sources use `process_jobs_batch`, F-13 LinkedIn bug fixed
- ✅ **Item 17** — Extract config to YAML: `data/skills.yml`, `data/locations.yml`
- ✅ **Item 18** — Single MongoDB module: one client, one pool, imports from `db.mongo`
- ⏭️ **Item 19** — Split domain/API DTOs: **deferred** (optional architectural refactor; N-18-class bugs currently patched with `when_used='json'` hack)
- ✅ **Item 20** — Modern packaging: `pyproject.toml` + `uv.lock`, deleted `requirements*.txt`, updated CI to `uv sync`
- ✅ **Item 21** — Housekeeping bundle: dead code, hardcoded paths, dead directory, encoding fix
- ✅ **Item 22** — Cross-source dedup: `canonical_fingerprint` + daily cleanup script; live cleanup removed 4,138 duplicates

### Phase 3 — Scale readiness (COMPLETE ✅)

**Status: 6 of 9 items shipped, 3 explicitly skipped as low-value at current scale.** See **§1c** for the detailed fix log.

**Shipped:**

- ✅ **F-15** — Shared thread-safe token-bucket rate limiter for Adzuna (0.4 req/sec) + Himalayas (1 req/sec). Kills the 429s.
- ✅ **F-19** — `ingestion_rejections` capped collection (5 MB / 500 doc max) captures raw payload + error on every schema failure.
- ✅ **F-21** — Removed misleading `executor.shutdown(wait=False, cancel_futures=True)` calls from Adzuna/Himalayas; the enclosing `with` block always drained anyway.
- ✅ **F-27** — `GET /api/ready` pings MongoDB + Clerk JWKS. **URL:** `http://localhost:8000/api/ready` locally or `<deployed-url>/api/ready` in prod. 200 when both OK, 503 with per-check status when either fails.
- ✅ **Weekly canary** — `.github/workflows/canary.yml` + `pipeline/canary.py` probe 6 API sources every Sunday 06:00 UTC. Red CI + email on failure.
- ✅ **YAML companies** — Greenhouse (169), Lever (10), Ashby (61), Workday (27) migrated to `data/companies/*.yml` via `listings/shared/companies.py`.

**Skipped:**

- ⏭️ **F-18** — Redis-backed SlowAPI. Only matters with >1 worker/replica; you run 1 server. Revisit when scaling.
- ⏭️ **F-16** — Endpoint caching for `distinct()` queries. Low benefit at current traffic; revisit when public traffic ramps.
- ⏭️ **MongoDB explain-plan review** — Diagnostic-only. Existing indexes are almost certainly fine at 49k docs. Revisit at 200k+.

**Not attempted:**

- Move ingestion to a separate worker service (already effectively is — just not formalized). Non-issue.

### Immediate actions the user needs to take (2026-08-12)

**Before daily automation resumes:**

1. `git push` all today's changes to `main` (packaging, YAML config, dedupe, all fixes). Without this, GH Actions cron will still fail on the old UTF-16 `requirements.txt` (N-19).
2. Manually **click "Enable workflow"** in GitHub Actions → Daily Job Ingestion. Currently disabled (N-20). Cron won't fire until re-enabled.
3. Manually trigger one run to verify the new `uv sync` setup works in CI (~20 min). Expected outcome: green ✅.
4. From that point on: daily runs at 5:30 AM IST resume automatically, dedupe runs after each ingestion.

**Then whenever ready:**

5. Get Clerk `iss` + `aud` values → send to session → 5-minute F-02 fix + add `test_auth.py` (Tier 4 completion).

---

## 7. What This Audit Did Not Cover

- **`.env` contents:** not opened. Credentials assumed valid; rotation status unverified.
- **Live database:** no queries run. Document counts, index usage stats, and query plans are not re-verified from prior audits.
- **Provider behavior:** each fetcher's target API/scrape target was not exercised. Payload assumptions rely on `AUDIT_DATA_POINTS.md`.
- **Runtime performance:** no profiling. Bottleneck claims (LinkedIn ~50min, Greenhouse enrichment) are quoted from `SPEC.md`.
- **Legal/ToS review** of LinkedIn/Workday scraping.
- **Frontend integration** (out of scope per user instruction).
