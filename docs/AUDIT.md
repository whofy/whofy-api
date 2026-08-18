# Whofy-API — Full Codebase Audit

> **Originally generated:** 2026-08-17
> **Last updated:** 2026-08-17, after the remediation pass (Phases A, B-partial, D-partial, plus a production index migration).
> **Scope:** every tracked file under `D:\whofy\whofy-api\`. Excludes `.venv/`, `__pycache__/`, `.pytest_cache/`.
> **Method:** every source file read end-to-end. Claims marked **[verified]** were reproduced by executing code in the project's own `.venv` (Python 3.12.2) or measured directly against the live Atlas cluster. Nothing here is inherited from prior audits.
> **Status at last update:** **23 of 51 findings fixed.** Test suite **183 → 211 passing**. Index footprint **283 MB → 30.6 MB [verified]**.

---

## 1. Executive summary

Whofy-API is a FastAPI monolith over MongoDB Atlas, plus a batch ingestion worker pulling nine job sources into a single `jobs` collection. The architecture is sound — nine sources normalize to one dict shape, funnel through one enrichment pipeline, one storage function, and one Pydantic model that gates every write. Nothing bypasses it. That single-funnel design is the codebase's main structural asset and is why most defects found here were one-file fixes rather than archaeology.

The original audit found 48 issues. Three more surfaced during remediation (§3). Of the 51 total, 23 are fixed, 6 were declined or deferred by the owner as deliberate decisions, and 22 remain open.

**The three most serious problems are resolved:**

1. **Dedup was deleting real jobs.** It grouped on company+title+location alone, so distinct requisitions at the same employer collapsed and all but one were deleted — nightly, re-deleting them after each ingestion restored them. Now cross-source only. **[FIXED]**
2. **Two confirmed data-loss defects in ingestion.** Workday postings with unparseable dates were silently schema-rejected; the source-cap path raised `TypeError` on mixed dated/undated batches. Both reproduced, both fixed, both pinned by tests. **[FIXED]**
3. **Indexes were 84% of the database.** Not in the original audit — found by measuring. A single text index on `(title, description)` was 253 MB against 72 MB of actual job data. **[FIXED — 252 MB reclaimed]**

**The most serious problem still open is auth** (S-01): tokens are signature-checked but `iss`, `aud`, and `azp` are not validated, so any token Clerk minted for this instance authenticates as its `sub`. Deferred pending the issuer value from the Clerk dashboard.

### Health snapshot

| Area | At audit | Now |
|---|---|---|
| API surface | Working | Working — unchanged |
| Ingestion correctness | **At risk** — 3 defects | **Good** — all three fixed and pinned |
| Retention semantics | **Inconsistent** — 14/28/30/28 | **One constant**, `RETENTION_DAYS = 14` |
| Storage footprint | **339 MB**, indexes 84% of it | **~86 MB**, indexes 26% of it |
| Ingestion resilience | One flaky source killed the night | Cleanup + scrapers + dedup survive partial failure |
| Auth | **Incomplete** | **Incomplete** — deliberately deferred |
| Cost / abuse control | Weak | **Weak** — owner declined a spend cap |
| Test coverage | 183 tests; none on auth/parsing/search | **211 tests**; auth caching + CORS now covered, parsing/search still bare |
| CI | Nothing runs the tests | **Nothing runs the tests** — declined |
| Observability | Print-based | Print-based — plus a working index audit tool |
| Deployment docs | None | None — deferred |

---

## 2. Remediation log — 2026-08-17

Ordered as executed. Every step ran the full suite; the two data-loss fixes and the dedup fix were additionally **mutation-tested** — the bug was reintroduced into the working file to confirm the new test actually failed, then reverted. A test that passes against broken code is not a guard.

### Phase A — data integrity

| ID | Fix | Evidence |
|---|---|---|
| **C-03** | `dedupe_jobs.py` now requires a group to span 2+ sources, and only deletes rows from losing sources. Added `--dry-run`. | Mutation test: old logic deleted 2 of 3 distinct same-source rows |
| **C-01** | Workday emits `None`, not `""`, for unparseable dates. `posted_at` added to the empty-string normalizer in `models/job.py`. | Reproduced original: `ValidationError` on `posted_at` |
| **C-02** | New `_posted_sort_key()` handles `datetime`, ISO string, and `None`. Runs before Pydantic coercion, so all three shapes are live. | Reproduced original: `TypeError: '<' not supported between 'datetime.datetime' and 'str'` |
| **C-04** | New `listings/shared/retention.py` — `RETENTION_DAYS = 14`, imported by storage, pipeline, and three fetchers. Chatbot prompt corrected from 28. | `tests/test_retention.py` asserts every consumer agrees |
| **C-05** | Deleted the unreachable cross-source-skip query and its always-zero counter. | Source name is embedded in the fingerprint; predicate unsatisfiable |
| **C-11** | `cleanup_non_english_jobs` counts first and returns early instead of spinning an 8-process pool to scan for rows that can't exist. | — |

New tests: `test_retention.py`, `test_undated_jobs.py`, `test_dedupe.py`. 183 → 199.

### Phase B — security and performance (partial)

| ID | Fix | Evidence |
|---|---|---|
| **S-05** | `get_current_user` memoizes on `request.state`. The limiter's key function and `Depends` each call it; now only the first pays for RSA verification. | Mutation test: without the memo, `assert 2 == 1` — verified twice |
| **S-06** | `_JWKS_CACHE` given a 1-hour TTL. Previously only invalidated on a `kid` miss. | — |
| **S-07** | CORS origins stripped and empties dropped — `"a, b"` no longer yields a dead `" b"`. | — |

New tests: `test_auth_caching.py`, `test_cors_origins.py`. 199 → 210.

**Correction to the original audit.** S-05 stated the blocking JWKS fetch runs on the event loop via both the limiter *and* `Depends`. The `Depends` half was wrong — FastAPI runs sync dependencies in a threadpool. Only the limiter's key function runs on the loop. With memoization, endpoints declaring `Depends(get_current_user)` resolve the dependency first (in the threadpool) and the limiter then reads the cache, so that path no longer blocks at all. A startup pre-warm was considered and rejected: it would fire a real network call on every one of the ~25 tests that boot the app, for a once-per-deploy benefit.

### Phase D — operations (partial)

| ID | Fix |
|---|---|
| **O-03** | `ingestion.yml` scraper and dedup steps now carry `if: ${{ !cancelled() }}`. One flaky source no longer aborts the job before they run. |
| **O-04** | Cleanup runs on partial source failure. Deletion needs `RETENTION_DAYS` of consecutive staleness, so one failed run can't delete anything — while skipping cleanup let the collection grow past the budget cleanup exists to protect. Still skipped when *every* source fails, which signals a systemic problem. |
| **O-08** | `.vscode/settings.json` re-saved as UTF-8. The prior audit claimed this fixed; it was not. |
| **O-09** | `audit_indexes.py` rewritten to deliver what its docstring promised — `collStats` sizes plus `$indexStats` usage counts, with an explicit caveat that counters reset on server restart. |
| **O-10** | Six spent one-shot migrations moved to `pipeline/archive/` with a README recording what each fixed and which code now handles it at write time. |
| **C-13** | `data/skills.yml`: 961 → 935 entries. |
| — | Dead code: unused imports across five fetchers, ten assigned-but-never-read timing variables, a duplicate import, a mid-file import moved to the header. |

`test_runners.py` updated (the old test pinned the behaviour O-04 changed) and one added for the total-failure case. 210 → 211.

### Index migration — the largest single win

Not in the original audit. Found by fixing `audit_indexes.py` and running it.

**Measured before [verified]:**

```
Data on disk    55.7 MB
Indexes        283.1 MB     ← 84% of the entire database
  title_text_description_text   253.5 MB   (90% of all index space)
  company_1__id_1                 2.4 MB   (0 reads)
```

The text index covered `description`. `/api/search` already discards any hit that only matched the description — its own comment calls them "noise" — so most of what that 253 MB produced was candidates the next stage threw away.

Replaced with `(title, required_skills)`: the same vocabulary, extracted at ingest, at a fraction of the size. `MAX_EXTRACTED_SKILLS` raised 15 → 25 first, because the cap was truncating skills off jobs listing many technologies.

**Measured after [verified]:**

```
Indexes   282.9 MB → 30.6 MB     (252.3 MB freed, 89%)
Total DB    ~339 MB → ~86 MB     (66% → 17% of the 512 MB free tier)
Rebuild time: 1.6s
```

Result-quality impact, measured on all 47,089 documents both before and after:

| Skill | Before | After | Change |
|---|---|---|---|
| Python | 7,036 | 7,029 | −0.1% |
| Kubernetes | 2,603 | 2,595 | −0.3% |
| React | 2,522 | 2,392 | −5% |
| SQL | 4,973 | 4,141 | −17% |

The SQL gap is mostly false positives being removed — the old description match was a substring check, so "SQL" matched inside "PostgreSQL", "MySQL", "NoSQL". React recovers further as ingestion re-saves jobs under the raised skill cap.

`ensure_indexes()` now self-heals: `_ensure_text_index` detects a text index covering the wrong fields and replaces it. MongoDB permits only one text index per collection, so this cannot be a build-then-swap — the drop must come first, leaving a window where `$text` queries fail. Measured at 1.6 seconds.

---

## 3. Findings discovered during remediation

**N-01 — the index footprint.** Covered above. **[FIXED]**

**N-02 — the chatbot breaks after ~15 exchanges. [OPEN — owner chose to keep current behaviour]**

`Chatbot.jsx:56` sends the entire conversation on every message. `messages` grows without bound; the backend caps `history` at 30 entries and **rejects** anything longer with a 422. Simulating the real frontend loop **[verified]**:

```
turn 16: FAILS -> history had 31 entries
    List should have at most 30 items after validation, not 31
```

The 16th message a user sends fails, and every one after it. The UI catches any failure as *"Sorry, I couldn't reach the server."* — so the user is told the server is down when it is working correctly and refusing on purpose. Reloading the page is the only escape, and nothing tells them that.

The 30-entry cap is deliberate (`test_chat_rejects_history_over_30_entries`, "Fix B regression guard") — sound reasoning against oversized payloads that didn't account for the frontend sending full history. The fix is to truncate to the newest 30 rather than reject, which preserves the abuse guard. The owner elected to keep the current behaviour.

**N-03 — `Elasticsearch` / `ElasticSearch` case collision.** `data/skills.yml` carried both spellings. `_SKILL_CANONICAL` is a dict comprehension keyed on lowercase, so the later entry won and `ElasticSearch` was the displayed form. Deduplication kept `Elasticsearch` (the official spelling); newly ingested jobs display that, existing rows keep the old casing until re-saved. **[FIXED, cosmetic]**

---

## 4. Findings register

**Status key:** ✅ FIXED · ⬜ OPEN · 🚫 DECLINED (owner decided against) · ⏸ DEFERRED (owner postponed)

### Critical / High

| ID | Finding | Status |
|---|---|---|
| C-03 | Dedup deleted distinct requisitions sharing company+title+location | ✅ |
| C-01 | Workday postings with unparseable dates silently schema-rejected | ✅ |
| C-02 | `save_jobs` cap path raised `TypeError` on mixed date types | ✅ |
| N-01 | Indexes were 84% of the database; one text index was 253 MB | ✅ |
| **S-01** | **JWT accepted without `iss` / `aud` / `azp` validation** | **⏸** |
| S-02 | `/api/chat` + `/api/upload-resume` unauthenticated, billing Groq | 🚫 |
| T-02 | Zero tests on the auth path | ⏸ (with S-01) |
| T-03 | Zero tests on `parsing/` — 236 lines, the product's front door | 🚫 |

**S-01 detail.** `fetch_api/auth.py:64-81` verifies signature and `exp` only. `sub` is then trusted for all `saved_jobs` reads and writes. Exposure is bounded — the JWKS comes from `api.clerk.com/v1/jwks` authenticated with this instance's secret key, so keys are instance-scoped, not global. But within the instance, any RS256 token from any JWT template authenticates as its `sub`, and no `azp` check pins the origin. The fix needs `CLERK_ISSUER` from the Clerk dashboard; it is written but not applied pending that value. Build it to **fail loudly at startup** if the issuer is unset — a wrong value 401s every authenticated request and breaks saved jobs entirely.

### Medium

| ID | Finding | Status |
|---|---|---|
| C-04 | Retention window disagreed across four subsystems | ✅ |
| C-05 | Cross-source-skip query structurally unreachable | ✅ |
| S-04 | Chat history entries unvalidated and unbounded; fabricated `assistant` turns possible | 🚫 |
| S-05 | JWT verified twice per request | ✅ |
| O-03 | One failing source aborted the whole nightly job | ✅ |
| O-04 | Cleanup skipped whenever any source failed | ✅ |
| **A-01** | `$facet` re-scores the entire match set on every page click; `/api/search` can run two full passes | ⬜ |
| **A-02** | `/api/locations` runs `distinct()` over the whole collection per cache miss, per worker; 16 MB BSON ceiling ahead | ⬜ |
| **C-06** | `_LEGAL_SUFFIXES_RE` strips bare `co`, over-collapsing distinct companies; all-punctuation names normalize to `""` | ⬜ |
| **C-07** | WWR drops postings with missing/unparseable `pubDate` instead of carrying them undated, as Lever does | ⬜ |
| **O-01** | `ThreadPoolExecutor.submit` monkey-patched globally at import time for log prefixes | ⬜ |
| **O-02** | ~400 duplicated lines: two near-identical runners, nine copy-pasted fetcher `main()`s, a duplicated search branch | ⬜ |

### Low

| ID | Finding | Status |
|---|---|---|
| C-11 | Non-English cleanup scanned for rows that can't exist | ✅ |
| C-13 | 25 duplicate entries in `skills.yml` | ✅ |
| N-03 | `Elasticsearch`/`ElasticSearch` case collision | ✅ |
| O-08 | `.vscode/settings.json` UTF-16 encoded | ✅ |
| O-09 | `audit_indexes.py` promised usage stats it never collected | ✅ |
| O-10 | Six spent one-shot scripts with no record of execution | ✅ |
| O-12 | Redundant `company_1__id_1` index, 0 reads, updated on every write | ✅ |
| S-06 | `_JWKS_CACHE` had no TTL | ✅ |
| S-07 | CORS origins not stripped | ✅ |
| T-06 | No tests for `dedupe_jobs.py` | ✅ |
| T-07 | Nothing pinned the retention constants together | ✅ |
| C-10 | Skills baked into `description` polluted the `$text` index | ✅ *(side effect — description no longer indexed; the duplication in stored text remains, cosmetic)* |
| S-03 | In-memory rate limiter: resets on deploy, multiplies per worker | ⬜ |
| S-08 | Stale unused `JWT_SECRET` in `.env` | ⬜ *(owner's file)* |
| S-09 | Unguarded `json.loads` of the Groq reply; `ValidationError` fallback can itself raise | ⬜ |
| S-10 | `/api/saved-jobs/ids` silently caps at 1,000 | ⬜ |
| C-08 | `data_quality_flags` written by two sources, read by nothing | ⬜ |
| C-09 | `detect_work_type` defaults to `On-site` with no signal — worst for Workday, whose detection text is title+location only | ⬜ |
| C-12 | Legacy `location_tokens: {$exists: false}` fallback emitted on every query | ⬜ |
| A-03 | Dead parameters: `_resolve_find_sort(has_skills)`, `_merge_location_branch(filt)` | ⬜ |
| A-05 | `postedAt: null` can't be distinguished from missing data | ⬜ |
| O-05 | ~100 `print()` calls; `logging` only in `parsing/` and `chatbot/` | ⬜ |
| O-06 | No README, no Dockerfile, no process config | ⏸ |
| O-07 | Shutdown hook constructs a Mongo client just to close it | ⬜ |
| O-11 | **No CI job runs the test suite** | 🚫 |
| D-01 | `fastapi==0.111.0`, `groq==0.9.0` well behind; no advisory scanning | ⬜ |
| D-03 | `langdetect` guarded by `try/except ImportError` despite being a hard dependency | ⬜ |
| T-04 | No tests for `/api/search`, the skill-ranked `/api/matches`, or `/api/jobs/{id}` | 🚫 |
| T-05 | No tests for `_clean_location_display` (~180 lines, user-visible) | 🚫 |

**Dead code still present:** `tech_filter.filter_tech_jobs` (unused by app code but has passing tests — left deliberately); `_get_clerk_jwks_url`'s vestigial local; unreachable `RAW_JOB_CAP` and unused `max_pages` default in Adzuna; unused pytest markers.

---

## 5. Architecture

```
                    ┌─────────────────────────────────────────┐
  Browser  ────────▶│  main.py  (FastAPI)                     │
                    │   CORS → GZip → SlowAPI limiter         │
                    └───┬──────┬───────┬──────────┬───────────┘
                        │      │       │          │
             fetch_api/ │      │       │ parsing/ │ chatbot/
               jobs.py  │  saved_jobs  │ resume   │ router
                        │      │       │          │
                        │      └─auth.py (Clerk JWKS, RS256)
                        │                 │          │
                        ▼                 ▼          ▼
                  db/mongo.py         Groq API   Groq API
                        │
                        ▼
              MongoDB Atlas — db "whofy"   (~86 MB, 12 indexes)
              ├── jobs                   47,089 docs
              ├── saved_jobs
              └── ingestion_rejections   (capped, 5 MB / 500 docs)
                        ▲
                        │  save_jobs()          ← validates against models/job.py
              ┌─────────┴──────────────────────────────────┐
              │  listings/shared/storage.py                │
              │   normalize → tokenize → fingerprint →     │
              │   validate(Job) → bulk upsert              │
              └─────────▲──────────────────────────────────┘
                        │  process_jobs_batch()  (ProcessPool)
              ┌─────────┴──────────────────────────────────┐
              │  listings/shared/pipeline.py               │
              │   age → tech filter → langdetect →         │
              │   skills / work_type / experience          │
              └─────────▲──────────────────────────────────┘
                        │        all cutoffs ← shared/retention.py
    ┌───────────────────┴────────────────────────────────────┐
    │ run_api.py (6 API sources)   run_scrapper.py (3 scrape) │
    │ greenhouse lever ashby       workday weworkremotely     │
    │ remoteok adzuna himalayas    hackernews                 │
    └────────────────────────────────────────────────────────┘
                        ▲
              GitHub Actions: ingestion.yml (daily 00:00 UTC)
                              canary.yml    (weekly Sun 06:00 UTC)
```

---

## 6. File inventory

Entries changed by remediation are marked **[updated]**.

### Application root

| File | Purpose | Notes |
|---|---|---|
| `main.py` | App factory, middleware, `/api/health`, `/api/ready` | **[updated]** CORS origins stripped. O-07 open: `lifespan` constructs a client at shutdown just to close it |
| `ingest_api.py` / `ingest_scrapper.py` | Entry points | Clean |
| `pyproject.toml` | 20 pinned runtime deps, 5 dev | D-01 open |
| `pytest.ini` | `asyncio_mode = auto`, `--strict-markers` | Two markers declared, applied to zero tests |
| `.env.example` | 7 env vars | Accurate; correctly omits the dead `JWT_SECRET` |
| `.gitignore` | | **[verified]** no `.env`, no `__pycache__` tracked |
| `.vscode/settings.json` | | **[updated]** now UTF-8 |

### Core modules

| File | Purpose | Notes |
|---|---|---|
| `config/settings.py` | `pydantic-settings`, `.env` from project root | Every secret `Optional` — a missing var surfaces at first use, not boot. Worth reconsidering for `MONGODB_URI` |
| `db/mongo.py` | `lru_cache`d sync + async clients, `certifi` | No explicit timeouts or pool sizing — an Atlas blip hangs a request for 30s on driver defaults |
| `models/job.py` | `Job`, `SavedJob`, `PyObjectId` | **[updated]** `posted_at` added to the empty-string normalizer. `DataQualityFlag` still written by two sources and read by nothing (C-08) |
| `listings/shared/retention.py` | **[new]** `RETENTION_DAYS = 14` | Single source of truth for every age cutoff |

### `fetch_api/`

| File | Purpose | Notes |
|---|---|---|
| `jobs.py` (724 lines) | 5 endpoints, filter builder, location cleaner | Largest file; three distinct concerns that want splitting. A-01, A-02, A-03, A-05, C-12 open. `_clean_location_display` still untested (T-05) |
| `saved_jobs.py` | 4 endpoints | Snapshot-fallback design is genuinely good. S-10 open |
| `auth.py` | Clerk JWKS, RS256 | **[updated]** per-request memoization, 1h JWKS TTL. S-01 still open — the weakest security surface in the repo |
| `limiter.py` | SlowAPI user-or-IP key | **[updated]** docstring notes the memoization. S-02/S-03 open |

### `parsing/`, `chatbot/`

| File | Purpose | Notes |
|---|---|---|
| `parsing/resume.py` | `POST /api/upload-resume` | Streams in 8 KB chunks, aborts mid-stream at 5 MB. Precise error mapping. **Zero tests** |
| `parsing/resume_parser.py` | Magic bytes, PyMuPDF/docx, Groq | Extension *and* signature check, `asyncio.to_thread`, LLM semaphore, anti-injection clause. **Zero tests.** S-09 open |
| `chatbot/chat_service.py` | Groq client + ~65-line system prompt | **[updated]** retention corrected to 14 days. Still enumerates customer names that will rot against the YAML |
| `chatbot/router.py` | `POST /api/chat` | S-04 and N-02 open by owner decision |

### `listings/shared/`

| File | Purpose | Notes |
|---|---|---|
| `storage.py` | `save_jobs`, cleanups, `ensure_indexes`, fingerprints, normalization | **[updated]** `_posted_sort_key`, `_ensure_text_index`, `TEXT_INDEX_FIELDS`, retention import, dead query removed, cleanup early-exit, `company` index dropped. The comment explaining why `last_seen_at` must be a `datetime` (BSON sorts every String below every Date, so one stray string would make cleanup match the whole collection) remains the best piece of institutional knowledge in the repo |
| `pipeline.py` | `process_single_job`, `process_jobs_batch` | **[updated]** imports `RETENTION_DAYS`; the false "same 28-day cutoff" comment corrected |
| `enrich.py` | Skills, work type, experience | **[updated]** `MAX_EXTRACTED_SKILLS` 15 → 25. C-09, C-10 notes above |
| `normalize.py` | HTML → text | Bounded unescape loop handles multiply-escaped entities correctly |
| `tech_filter.py` | Whitelist / blacklist regexes | Blacklist-first ordering correct. `filter_tech_jobs` unused but tested |
| `companies.py` | `lru_cache`d YAML loader | Clean |
| `rate_limiter.py` | Thread-safe `TokenBucket` | Correct — releases the lock before sleeping |

### Fetchers

All nine share one shape; their `main()` bodies remain near-verbatim copies (O-02). **[updated]** — unused imports and dead timing variables removed across Ashby, Lever, Adzuna, RemoteOK, Himalayas, WWR, Greenhouse.

| Fetcher | Notes |
|---|---|
| `greenhouse` | 169 boards. **[updated]** duplicate import removed |
| `lever` | 10 boards. Only source deliberately setting `posted_at: None` |
| `ashby` | 61 boards. Handles `location` as str or dict |
| `adzuna` | Best error handling in the repo — backoff, `RateLimitExhausted`, `cancel_futures`. Two dead knobs remain |
| `remoteok` | Only source with a direct `logo_url` |
| `himalayas` | **[updated]** retention import; 4 unused enrich imports removed. The ordered-consumption comment documents a real, subtle concurrency bug fixed properly |
| `hackernews` | Serial comment fetch with 0.3s sleep — minutes on a large thread. `BATCH_SIZE` implies batching that doesn't exist |
| `weworkremotely` | **[updated]** retention import, unused `re` removed. C-07 open |
| `workday` | **[updated]** `posted_at` now `None` not `""`; retention import. Detection text is title+location only, so C-09 bites hardest here |

### `pipeline/`

| File | Status |
|---|---|
| `dedupe_jobs.py` | **[updated]** cross-source only, `--dry-run` added. Runs daily in CI. Now tested |
| `migrate_text_index.py` | **[new]** one-shot index migration; applied 2026-08-17 |
| `audit_indexes.py` | **[updated]** real `collStats` + `$indexStats` reporting |
| `canary.py` | Weekly probe. Docstring mentions a LinkedIn source that doesn't exist |
| `cleanup.py`, `backfill_enrichment.py` | Live. `backfill_enrichment` loads the whole collection into memory with no batching — will OOM at scale |
| `archive/` | **[new]** six spent one-shots + a README recording what each fixed |

### `data/`, `.github/`

| File | Notes |
|---|---|
| `companies/*.yml` | **[verified]** 169/61/27/10 entries, uniform key shapes, zero duplicate names, zero missing domains |
| `skills.yml` | **[updated]** 961 → 935 |
| `locations.yml` | 49 countries, 59 cities, 52 states. 59 cities is thin for a global board |
| `ingestion.yml` | **[updated]** later steps carry `if: ${{ !cancelled() }}` |
| `canary.yml` | Correct and minimal |
| — | **No workflow runs the tests** (O-11) |

---

## 7. What's genuinely good

Unchanged from the original audit, and worth preserving through any refactor:

**The BSON type invariant and its guard test.** `storage.py` explains why `last_seen_at` must be a real `datetime`: in BSON sort order every String sorts below every Date, so one stray string field would make `cleanup_expired_jobs` match the entire collection. `tests/test_datetime_types.py` pins it. A near-miss catastrophic bug, correctly understood and defended.

**The Himalayas ordered-consumption fix.** Pages must be consumed in ascending-offset order, not completion order — the API returns newest-first, so early-stop is only valid once every earlier page is read. Otherwise a fast high-offset page ends the loop while recent pages are in flight, dropping data non-deterministically.

**The Motor `.limit()` note.** `to_list(length=…)` is a batch-size hint, not a cursor cap — omitting `.limit()` made page 2 return every remaining row.

**The Lever undated-jobs fallback.** `{"$gte": cutoff}` never matches `null`, so filtering on `posted_at` alone made every Lever job vanish when a user picked any Posted filter.

**The `$and` accumulator.** Assigning `filt["$or"]` directly means the second such clause silently overwrites the first, and both location and posted need one.

**Single-funnel ingestion.** Nine sources, one dict shape, one pipeline, one storage function, one model gating the write.

**Config as data.** Company lists, skills, and location vocabulary all in YAML behind a validating loader. Fully realized — no hardcoded list remains.

**The `saved_jobs` snapshot fallback.** A bookmark degrades to `expired: true` instead of 404-ing when its row is cleaned up.

**`conftest.py`'s docstring.** Documents three non-obvious pytest/FastAPI interactions that cost most people an afternoon each: module-load import binding, `Depends` capturing refs at router-definition time, and `mongomock` sharing state across clients.

---

## 8. What's left

### Needs a decision

| Item | Blocked on |
|---|---|
| **S-01** — issuer/audience validation | `CLERK_ISSUER` from the Clerk dashboard |
| **S-08** — remove `JWT_SECRET` from `.env` | Owner's file |

### Declined — recorded so the consequences are on the record

| Item | Standing consequence |
|---|---|
| S-02 — spend cap | Resume upload and chat are open to anonymous use, bounded only by a per-IP limiter that resets on deploy |
| S-04 / N-02 — chat history | Chat fails from the 16th message of any conversation; entries remain unvalidated and unbounded |
| O-11 — CI | 211 tests run only when someone remembers |
| T-03/T-04/T-05 — Phase C | Resume upload, search, and the location dropdown remain untested |

### Open, unscheduled

**Refactors:** O-01 (global monkey-patch), O-02 (~400 duplicated lines), O-06 (README).

**Correctness:** C-06, C-07, C-08, C-09, C-12, A-03, A-05, S-09, S-10, O-07, D-03.

**Scale — none of these matter at current size:** A-01 (search result caching), A-02 (precompute the location dropdown), S-03 (Redis limiter), O-05 (structured logging). Revisit when something actually hurts.

**Hygiene:** D-01 (dependency currency and advisory scanning).

---

## 9. Verification appendix

All commands run from `D:\whofy\whofy-api` against the project's `.venv` (Python 3.12.2).

**Test suite:**

```bash
.venv/Scripts/python.exe -m pytest -q --no-header
# 183 passed  (at audit)  →  211 passed  (after remediation)
```

**C-01 / C-02 reproduced before fixing:**

```python
Job.model_validate({**base, "posted_at": ""})
# → ValidationError on `posted_at`

sorted([{"posted_at": now}, {"posted_at": None}],
       key=lambda j: j.get("posted_at") or "", reverse=True)
# → TypeError: '<' not supported between 'datetime.datetime' and 'str'
```

**Mutation testing** — bugs reintroduced into the working files, tests re-run, then reverted:

```
TypeError: '<' not supported between 'datetime.datetime' and 'str'   (C-02)
assert 2 == 0   # dedup deleted two distinct same-source rows        (C-03)
assert 2 == 1   # dedup took the winning source's second row         (C-03)
assert 2 == 1   # token verified twice for one request               (S-05)
```

**N-02 reproduced** by simulating the real `Chatbot.jsx` loop:

```
turn 16: FAILS -> history had 31 entries
```

**Index measurement**, before and after:

```bash
.venv/Scripts/python.exe pipeline/audit_indexes.py
.venv/Scripts/python.exe pipeline/migrate_text_index.py --dry-run
.venv/Scripts/python.exe pipeline/migrate_text_index.py --apply
# 282.9 MB → 30.6 MB, 252.3 MB freed (89%), rebuild 1.6s
```

**Secrets hygiene:**

```bash
git ls-files | grep -E "\.env"      # → .env.example only
git ls-files | grep -c pycache      # → 0
grep -rn "JWT_SECRET" --include="*.py" . --exclude-dir=.venv   # → 0 hits
```

**Static checks:** `pyflakes` could not be installed (`pip` absent from the venv). Dead-code findings were confirmed by targeted `grep` for each symbol's usage within its own module, and every touched module was import-checked after editing.

---

*Every file listed in §6 was read in full. Every number marked **[verified]** was produced by running the code, not by inspection.*
