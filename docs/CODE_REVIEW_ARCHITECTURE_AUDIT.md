# WHOFY API — Detailed Code Review and Architecture Audit

> **Review date:** 2026-08-08  
> **Scope:** `whofy-api/` only  
> **Change policy:** This is a new audit document. Existing files under `docs/` were read but not modified.  
> **Review type:** Static code and architecture review; no production data was changed.

## 1. Executive summary

WHOFY is a sensible early-stage product shape: FastAPI serves a read-heavy job-search API, MongoDB stores denormalized job documents, and scheduled ingestion collects from heterogeneous job providers. The current code is understandable and already contains useful separation in places such as `listings/shared/pipeline.py`, Pydantic models, source-specific fetchers, and a shared `save_jobs()` path.

The highest-risk problems are correctness and operational visibility, not raw throughput:

1. **Job freshness can be wrong.** Expiry uses a string cutoff against BSON dates and is based primarily on `added_at`, so actively observed jobs can be removed while stale jobs can survive. Date-age filtering also silently bypasses `datetime` values.
2. **Ingestion can report success after source failures.** Both runners catch exceptions, print them, and continue. CI can therefore be green while one or more providers failed.
3. **Authentication is incomplete.** Clerk JWT signature and expiry are checked, but issuer and audience are not. JWKS retrieval is synchronous inside an async request path.
4. **Costly endpoints are insufficiently bounded.** Chat, resume parsing, and public job-search queries can consume upstream API, CPU, memory, or MongoDB resources without strong body/history/query budgets.
5. **The documented common pipeline is not the actual pipeline.** Workday, We Work Remotely, Hacker News, and LinkedIn perform enrichment/filtering directly in their adapters, while the architecture document says every source should use the shared pipeline.
6. **The application has no reliable safety net.** The repository has smoke scripts, but no asserted unit/integration test suite covering persistence, dates, auth claims, provider contracts, or API responses.

### Overall assessment

| Area | Assessment | Why |
|---|---|---|
| Product architecture | **Good prototype / needs hardening** | The domain boundaries are visible, but ingestion and API layers are coupled through `listings/shared`. |
| Data correctness | **High risk** | Date types, freshness semantics, deduplication, and silent schema rejection can change what users see. |
| Security | **Medium-high risk** | JWT claim validation, expensive public endpoints, upload limits, and error disclosure need attention. |
| Reliability | **High risk** | Provider failures are swallowed and there is no run ledger or per-source health state. |
| Scalability | **Adequate for a small launch; weak beyond it** | MongoDB can support the workload, but current queries, in-memory collections, and synchronous ingestion paths will become bottlenecks. |
| Maintainability | **Medium risk** | Copy-pasted runners, hard-coded provider catalogs, unused imports, and drift between docs and code increase change risk. |

## 2. Current architecture as implemented

```text
                         ┌──────────────────────────┐
                         │ FastAPI process           │
                         │ main.py                   │
                         └────────────┬─────────────┘
                                      │
       ┌──────────────────────────────┼──────────────────────────────┐
       │                              │                              │
 jobs/search routes             saved-jobs/auth                 chat/resume
 fetch_api/jobs.py              saved_jobs.py                   chatbot/, parsing/
       │                              │                              │
       └──────────────┬───────────────┴──────────────┬───────────────┘
                      │                              │
                Motor async client             Groq / Clerk / files
                      │
                 MongoDB Atlas

 GitHub Actions / manual scripts
        │
        ├── ingest_api.py → listings/run_api.py
        └── ingest_scrapper.py → listings/run_scrapper.py
                                  │
                    ThreadPoolExecutor per source
                                  │
              provider fetchers + mixed inline enrichment
                                  │
                 shared pipeline (only some sources)
                                  │
                  synchronous PyMongo storage.py
                                  │
                         MongoDB Atlas
```

### Architectural diagnosis

This is currently a **modular monolith with an external batch process**, not a microservice system. That is an appropriate choice for a mini startup. The principal boundary problem is that the API imports enrichment and normalization internals from `listings/shared` (`fetch_api/jobs.py`), while ingestion owns MongoDB persistence directly. The result is two application modes with different clients, lifecycles, error handling, and contracts.

Do not split into many network services yet. First create stable internal interfaces and a separate worker process. A queue, Redis cluster, or multiple databases should be introduced only when actual throughput, latency, or failure isolation requires them.

## 3. Prioritized findings

Severity meanings: **P0** can cause security exposure, destructive data behavior, or a materially false system state; **P1** can cause frequent incorrect behavior, outages, or uncontrolled cost; **P2** is an important reliability/maintainability issue; **P3** is cleanup or future hardening.

| ID | Sev. | Area | Finding | Primary location |
|---|---:|---|---|---|
| F-01 | P0 | Data lifecycle | Expiry compares a string ISO cutoff with MongoDB date fields and uses `added_at` rather than `last_seen_at`. | `listings/shared/storage.py:429-442` |
| F-02 | P0 | Auth | JWT `iss` and `aud` are not validated; a valid RS256 token from an unintended issuer/audience may be accepted. | `fetch_api/auth.py:54-81` |
| F-03 | P0 | Ingestion state | Source exceptions are caught and not returned to the runner, so CI may succeed after partial ingestion failure. | `listings/run_api.py:37-53`, `listings/run_scrapper.py:38-52` |
| F-04 | P1 | Data correctness | `_is_too_old()` assumes a string. Provider adapters commonly pass `datetime`; `TypeError` is caught and old jobs are accepted. | `listings/shared/storage.py:221-230`, API fetchers |
| F-05 | P1 | Deduplication | The fingerprint includes `source`, so it cannot deduplicate equivalent jobs across sources; the cross-source counter is misleading. | `listings/shared/storage.py:35-37,275-293` |
| F-06 | P1 | Saved jobs | `ObjectId(req.job_id)` is evaluated before the `try`; invalid IDs become 500s. Delete has the same issue. | `fetch_api/saved_jobs.py:25-33,62-68` |
| F-07 | P1 | Saved jobs | Check-then-insert permits duplicate saves under concurrency; there is no unique `(user_id, job_id)` index. | `fetch_api/saved_jobs.py:25-50`, `storage.py:449-458` |
| F-08 | P1 | Saved jobs | Results are capped at 1,000 without pagination; expired responses return a raw `ObjectId` instead of a guaranteed JSON string. | `fetch_api/saved_jobs.py:75-111,118-120` |
| F-09 | P1 | Abuse/cost | Chat and resume endpoints have no application rate limit, and chat history/message sizes are unbounded. | `chatbot/router.py:9-18`, `parsing/resume.py:19-55` |
| F-10 | P1 | Upload safety | The 10 MB check relies on optional `UploadFile.size`; the code then reads the entire body without enforcing a post-read limit or checking file signatures. | `parsing/resume.py:28-34` |
| F-11 | P1 | LLM contract | `RESUME_SCHEMA` is declared but not sent to Groq and the JSON response is not validated with Pydantic. | `parsing/resume_parser.py:19-29,84-91` |
| F-12 | P1 | Ingestion contract | Workday, WWR, HN, and LinkedIn bypass `process_jobs_batch()` and run enrichment/filtering inline. | Their `fetcher.py` files; `docs/INGESTION_ARCHITECTURE.md` |
| F-13 | P1 | Provider safety | LinkedIn stores a `datetime`, but both age/enrichment paths call string methods. Re-enabling the source will fail. | `listings/scraping/linkedin/fetcher.py:79-89,135,247-263` |
| F-14 | P1 | Provider safety | Workday contains duplicate `description` keys; the final `None` overwrites the earlier value. | `listings/scraping/workday/fetcher.py:231-242` |
| F-15 | P1 | Rate limiting | Adzuna uses three independent workers with a one-second delay, so the global free-tier quota is not actually enforced. | `listings/adzuna/fetcher.py:16,111-139,181-214` |
| F-16 | P1 | Query cost | `distinct()` endpoints materialize all values, and search/matches allow up to 1,000 records plus aggregation over descriptions. | `fetch_api/jobs.py:120-220,279-307` |
| F-17 | P2 | Event loop | Clerk JWKS retrieval uses blocking `requests.get()` inside a FastAPI dependency. | `fetch_api/auth.py:19-30` |
| F-18 | P2 | Rate limiter | SlowAPI uses process-local memory; limits multiply across workers and are not shared across replicas. | `fetch_api/limiter.py:20-24` |
| F-19 | P2 | Persistence | Schema-invalid jobs are counted and discarded with no quarantine document or sample payload. | `listings/shared/storage.py:301-333` |
| F-20 | P2 | Freshness | `last_seen_at` is updated, but cleanup does not use it for normal documents. | `listings/shared/storage.py:307-315,429-442` |
| F-21 | P2 | Cancellation | Adzuna and Himalayas call `shutdown(wait=False)` inside executor context managers; context exit still waits for running work. | Their `fetcher.py` files |
| F-22 | P2 | Resource lifecycle | Sync and async Mongo clients are separate; the API closes only the async client, while storage creates a separate singleton. | `db/mongo.py`, `listings/shared/storage.py` |
| F-23 | P2 | Tests | Existing test files are print-based smoke scripts with no assertions; the repository has no meaningful unit/integration coverage. | `test_rate_limit*.py`, `listings/adzuna/fetcher_test.py`, `tests/` |
| F-24 | P2 | Reproducibility | `requirements.txt` is pinned, but there is no Python lock/export with hashes, `pyproject.toml`, Dockerfile, or deployment manifest. | Repository root |
| F-25 | P3 | Maintainability | `run_api.py` and `run_scrapper.py` duplicate logger, monkey-patching, semaphore, and orchestration patterns. | Both runner files |
| F-26 | P3 | Operations | Hard-coded company catalogs require code changes and redeployments for routine source maintenance. | Provider `COMPANIES` constants |
| F-27 | P3 | Health | `/api/health` returns OK without checking MongoDB or critical dependencies. | `main.py:38` |
| F-28 | P3 | Documentation | Existing audit/spec documents describe fixes that are not enforced and contain stale repository claims. | `docs/AUDIT.md`, `docs/AUDIT_DATA_POINTS.md`, `docs/INGESTION_ARCHITECTURE.md`, `docs/SPEC.md` |

## 4. Detailed finding notes and recommended fixes

### 4.1 P0/P1 data correctness and persistence

#### F-01 / F-20 — expiry semantics are unsafe

`save_jobs()` converts `added_at` and `last_seen_at` through the `Job` model, which produces datetime values for MongoDB. `cleanup_expired_jobs()` then builds `cutoff` with `.isoformat()` and compares it using `$lt`. MongoDB comparisons are type-sensitive; the cleanup query must use the same timezone-aware Python `datetime` type as the stored field.

The more important semantic issue is that normal documents are deleted based on `added_at`. A job first seen 40 days ago but observed during today's successful fetch is still eligible for deletion. This particularly affects sources with weak or missing `posted_at` data. The intended rule should be explicit:

- `last_seen_at` controls whether an active source still reports the job.
- `posted_at` controls user-facing age filters when reliable.
- `added_at` is historical metadata, not the normal expiry clock.
- Cleanup should delete only when a source has completed a trustworthy run and the job has not been seen for the configured source grace period.

**Recommended fix:** store `datetime.now(timezone.utc)` directly, query with a datetime cutoff, and define a source-run watermark. Do not delete jobs merely because one provider run was incomplete. Add tests for native dates, missing dates, active-but-old records, and failed source runs.

#### F-04 — age filtering silently accepts old jobs

`_is_too_old(posted_at: str)` calls `posted_at.replace("Z", "+00:00")`. Greenhouse, Ashby, RemoteOK, Adzuna, Hacker News, and parts of the other pipeline provide Python `datetime` values. Calling the string replacement form on a datetime raises `TypeError`; the broad exception handler returns `False`, which means “not too old.” This is a silent correctness failure rather than a visible crash.

**Recommended fix:** define one date normalizer accepting `str | datetime | None`, reject or quarantine malformed dates, and use it at the adapter boundary. Avoid broad exception handling that converts data contract violations into acceptance.

#### F-05 — cross-source deduplication is not cross-source

`_fingerprint()` creates `source || source_job_id`. Since the source is part of the fingerprint, the same logical job from two providers normally receives different fingerprints. The query that looks for existing fingerprints also excludes the current source. The code therefore cannot perform the cross-source deduplication described by the field name and existing documents.

**Recommended fix:** separate keys by purpose:

- `source_key = (source, source_job_id)` for provider identity and upsert uniqueness.
- `canonical_fingerprint` built from normalized company, title, location, and apply URL for a probabilistic cross-source duplicate signal.
- Keep the original provider identity for traceability.

Do not make fuzzy deduplication destructive until it has an audit mode and measured false-positive rate.

#### F-06 — invalid saved-job IDs become server errors

In `save_job()`, the first `ObjectId(req.job_id)` occurs while constructing the `find_one()` filter, before the `try` block. In `unsave_job()`, the conversion is also outside error handling. A malformed ID therefore bypasses the intended 400 response.

**Recommended fix:** validate once at the top of each route, return `400`, and reuse the validated `ObjectId`. Use `ObjectId.is_valid()` or a shared dependency. Catch `DuplicateKeyError` separately after adding a unique index.

#### F-07 — saved-job uniqueness is application-only

Two concurrent requests can both observe no existing record and both insert. This is a classic check-then-insert race. The database must enforce the invariant.

**Recommended index and write pattern:**

```text
saved_jobs: unique { user_id: 1, job_id: 1 }
saved_jobs:       { user_id: 1, saved_at: -1 }
```

Use an atomic `update_one(..., {$setOnInsert: ...}, upsert=True)` or treat `DuplicateKeyError` as `already_saved`. Add a migration/verification step before enabling the unique index so existing duplicates are handled intentionally.

#### F-08 — saved-job pagination and serialization

The routes always read at most 1,000 records. There is no `skip`, cursor, or `has_more`, so the API silently truncates a user's collection. For an expired job, `"id": saved["job_id"]` can remain an `ObjectId`, unlike the normal serializer's string ID.

**Recommended fix:** use cursor pagination ordered by `(saved_at, _id)`, return a stable page envelope, and serialize IDs at the boundary. Decide whether snapshots are immutable and version them if the response contract evolves.

#### F-19 — rejected jobs disappear without diagnosis

`save_jobs()` catches every exception from `Job.model_validate()` and increments `schema_rejected`. The source receives only a count; no reason, field name, provider, or bounded sample is retained. When a provider changes its payload, the ingestion can look healthy while silently losing records.

**Recommended fix:** record a bounded `ingestion_rejections` document containing run ID, source, source job ID, error class/message, schema version, and a redacted payload excerpt. Add metrics for rejected percentage and make a high rejection ratio fail the source run.

### 4.2 P0/P1 security, abuse, and external services

#### F-02 — JWT validation is incomplete

`jwt.decode()` restricts the algorithm to `RS256` and verifies expiry by default, which is good. However, it explicitly disables audience validation and supplies no issuer validation. The backend should accept only tokens issued for this Clerk instance and intended for this API.

**Recommended fix:** configure expected issuer and audience from settings, pass `issuer=...`, `audience=...`, and validate any required `azp`/authorized-party policy. Keep the error returned to clients generic; log the detailed reason internally. Add tests for wrong issuer, wrong audience, expired token, unknown key, missing subject, and key rotation.

#### F-17 — JWKS retrieval blocks the async server

`get_current_user()` can call `_fetch_jwks()`, which performs synchronous `requests.get()` with a ten-second timeout. A slow Clerk response consumes the FastAPI worker thread/event loop path. JWKS errors are also not translated consistently into a controlled 401/503 response.

**Recommended fix:** use an async HTTP client created at application lifespan, cache keys with a TTL, refresh on `kid` miss, protect refresh with a lock, and define stale-cache behavior. If a sync client remains temporarily, run it in a thread and ensure one request cannot trigger repeated refreshes.

#### F-09 — AI endpoints need product-level quotas

`slowapi` limits the job routes but not `/api/chat` or `/api/upload-resume`. Both can trigger paid Groq requests. Chat history is an unconstrained `list[dict]`; every entry is forwarded to Groq, and the request has no maximum message or history length. Resume parsing accepts a body that may be larger than the advertised limit and performs CPU-heavy extraction plus a paid LLM call.

**Recommended limits:**

- Per-IP and, when authenticated, per-user quotas for chat and resume parsing.
- Maximum chat message characters, history entries, and total history characters.
- Maximum resume bytes enforced while reading, not only from metadata.
- Content-type and magic-byte validation for PDF/DOCX.
- Concurrency semaphore for LLM calls and a short upstream timeout.
- Metrics for token/call consumption and 429 responses.

#### F-10 — upload handling is memory-unbounded

`UploadFile.size` is optional and is not a substitute for a streaming limit. `await file.read()` loads the entire upload before `parse_resume()`. A client can omit or falsify the size metadata and send a large body.

**Recommended fix:** read in chunks up to `MAX_FILE_SIZE + 1`, reject when the extra byte is observed, then pass the bounded bytes to extraction. Validate the extension, MIME type, and file signature. Consider an isolated worker for hostile or malformed documents.

#### F-11 — resume output has no enforced schema

`RESUME_SCHEMA` is dead configuration. The Groq request asks for a generic JSON object, and `json.loads()` accepts any valid JSON object. The prompt also says a maximum of 25 skills while the existing data-point document says 15. Downstream clients can receive missing keys, wrong types, oversized arrays, or unexpected fields.

**Recommended fix:** define a Pydantic `ResumeResult` with field bounds and use it after JSON decoding. If the provider supports strict structured output, send the schema in the provider-supported format; still validate locally. Return a stable internal error for malformed model output without exposing the raw exception.

#### F-16 — public queries can become expensive

`/api/locations` and `/api/companies` call `distinct()` and then materialize all values in Python. Search and matches allow a page of up to 1,000 records and use `$indexOfCP` over title/description fields in aggregation. This is acceptable for a small data set but becomes a predictable load multiplier as job count and public traffic grow.

**Recommended fix:** cache filter dictionaries with a short TTL, normalize/filter values during ingestion, use bounded page sizes, add query timing metrics, and consider a dedicated search projection or search engine once relevance requirements outgrow MongoDB text indexes. Keep user-controlled regex out of queries; the current location filter correctly escapes values.

### 4.3 P1 ingestion and provider reliability

#### F-03 — failures are swallowed at the wrong boundary

`run_source_concurrently()` catches `Exception`, prints an error, and returns `None`. The outer `future.result()` sees a successful future. Provider adapters also often catch `requests.RequestException` and return an empty list, making “provider returned zero jobs” indistinguishable from “provider was down.” Cleanup then runs as if the whole run were valid.

**Recommended fix:** return a structured `SourceRunResult` with status, fetched, accepted, rejected, upserted, duration, and error. Classify failures as `success`, `partial`, `failed`, or `skipped`. Persist a run record. Fail CI when a critical source fails or when the aggregate failure/rejection rate exceeds a threshold. Never expire a source's jobs after an untrusted run.

#### F-12 — four adapters violate the documented handoff

The shared pipeline is used by the API-based sources, but Workday, WWR, HN, and LinkedIn perform some or all of HTML conversion, skill extraction, language/tech filtering, work-type detection, and experience detection themselves. This creates different semantics for the same fields, repeats code, and makes performance claims in `docs/INGESTION_ARCHITECTURE.md` unreliable.

**Recommended contract:** every adapter returns only:

```text
RawListing(source, source_job_id, title, company, location,
           raw_description, apply_url, posted_at, provider_metadata)
```

The orchestrator then runs normalize → tech filter → language filter → enrichment → validation → persistence. Provider-specific exceptions should be isolated to parsing the provider response, not business enrichment.

#### F-13 — LinkedIn is disabled but not safe to re-enable

`_parse_search_page()` converts the date into a `datetime`. `_is_within_age()` expects a string and catches the resulting `TypeError`, allowing the record through. `_enrich_listings()` then calls `.replace("Z", "+00:00")` on the datetime without a catch, which can terminate the source.

**Recommended fix:** apply the shared date normalizer and add a disabled-source contract test that parses representative HTML without making network calls. Keep the source disabled until rate limits, legal/terms review, concurrency, and failure behavior are explicitly addressed.

#### F-14 — Workday description overwrite

The normalized Workday dictionary contains `description` twice. Python keeps the last value, so the earlier baked description is discarded and the final value is `None`. The data-quality flag is therefore consistent with the final value, but the code is misleading and may discard useful title-based content.

**Recommended fix:** remove the duplicate key and decide deliberately whether a title/location-derived description is useful. If Workday has no description, preserve `None` and keep skills in explicit fields rather than manufacturing a description that looks source-provided.

#### F-15 / F-21 — provider throttling and cancellation

Adzuna's delay is local to each of three workers, not a shared quota. The task list is also fully submitted before the code learns that quota is exhausted. Calling `shutdown(wait=False, cancel_futures=True)` within a `with ThreadPoolExecutor(...)` does not make the context exit immediately; queued/running work can still delay the run.

Himalayas has the same cancellation shape when an old page is found. The fetcher queues all offsets before it knows whether it can stop.

**Recommended fix:** implement a shared token-bucket limiter per provider, submit work incrementally, stop scheduling after quota exhaustion, and use a bounded producer/consumer design. Measure actual request rates rather than relying on per-thread sleeps.

### 4.4 P2/P3 platform and maintainability issues

#### F-18 — rate limits do not scale horizontally

`Limiter` defaults to process-local storage. One worker has one bucket; four workers or two replicas can allow roughly four or two times the configured traffic. The comment acknowledges this but the production fallback is not implemented.

**Recommended fix:** use Redis-backed SlowAPI storage before adding replicas. Trust proxy headers only from a configured proxy, otherwise IP-based limits can be bypassed or incorrectly shared.

#### F-22 — separate database client lifecycles

`db/mongo.py` provides cached sync and async clients, while `listings/shared/storage.py` creates its own sync singleton. This is not inherently incorrect, but it creates separate pools and separate lifecycle/timeout configuration. The API lifespan closes only the async client. One shared data-access configuration should define pool sizes, server selection timeout, retry policy, and shutdown behavior.

Keep sync PyMongo in a worker process if desired; do not use it in the async request path. The target architecture below preserves that separation explicitly rather than hiding it behind multiple globals.

#### F-23 — current tests do not protect behavior

`test_rate_limit.py` requires a separately running server and only prints results. `test_rate_limit_auth.py` has no assertions and its route requests can depend on a live database. `listings/adzuna/fetcher_test.py` is a manual variant of the fetcher rather than a test suite. `tests/fixtures/.gitkeep` confirms there is no meaningful fixture set.

At minimum, add deterministic tests for:

- Date normalization and cleanup filters.
- Job validation and schema rejection/quarantine.
- Saved-job invalid IDs, duplicate writes, pagination, and expired snapshots.
- JWT issuer/audience/key-rotation behavior with mocked JWKS.
- Shared pipeline contract using fixture HTML/JSON.
- One parser fixture per provider, with no network access.
- API route responses using mocked repositories.

## 5. Recommended scalable architecture

### 5.1 Near-term target: modular monolith plus ingestion worker

For WHOFY's current stage, the best architecture is one deployable API and one independently scheduled worker, sharing domain packages and MongoDB but not sharing an event loop or process:

```text
                         ┌─────────────────────┐
                         │ API service          │
                         │ FastAPI / async      │
                         └──────────┬──────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
              API repositories                  AI gateway
                    │                               │
                    └───────────────┬───────────────┘
                                    │
                              MongoDB Atlas
                                    │
            ┌───────────────────────┴───────────────────────┐
            │                                               │
   ingestion_runs / jobs / saved_jobs / logos       object storage (optional)

┌─────────────────────┐       queue or scheduled job       ┌──────────────────┐
│ Ingestion worker     │ ─────────────────────────────────▶ │ Provider adapters │
│ sync I/O + CPU pool │                                    │ fetch only        │
└──────────┬──────────┘                                    └────────┬─────────┘
           │                                                        │
           └──── normalize → filter → enrich → validate → upsert ───┘
```

This is scalable enough for a mini startup because it provides process isolation and stable contracts without operationally expensive microservices.

### 5.2 Suggested package boundaries

```text
whofy-api/
├── app/
│   ├── main.py                 # app factory and lifespan
│   ├── api/                    # HTTP routers, request/response DTOs
│   ├── auth/                   # Clerk/JWKS verification
│   ├── services/               # use cases: search, saved jobs, resume, chat
│   ├── repositories/           # async Mongo repositories only
│   └── clients/                # Groq, Clerk, logo provider, HTTP clients
├── domain/
│   ├── jobs.py                 # canonical domain models and date rules
│   ├── saved_jobs.py
│   └── ingestion.py            # run/status/value objects
├── ingestion/
│   ├── worker.py               # run lifecycle, source scheduling
│   ├── contracts.py            # RawListing and SourceRunResult
│   ├── adapters/               # greenhouse, lever, etc.; fetch/map only
│   ├── processing/             # normalize, tech/language filters, enrich
│   └── persistence.py          # sync worker repository and bulk upserts
├── migrations/                 # versioned, idempotent migrations
├── tests/
│   ├── unit/
│   ├── contract/
│   └── integration/
├── pyproject.toml
└── uv.lock or requirements lock/export
```

A full directory move is not required immediately. The important first step is to make `domain` and `ingestion/contracts` independent of HTTP, then make `fetch_api/jobs.py` stop importing from `listings/shared`.

### 5.3 Data model and MongoDB indexes

Keep MongoDB initially, but make invariants explicit:

#### `jobs`

- Unique `(source, source_job_id)`.
- `canonical_fingerprint` non-unique initially for review/analytics.
- Native UTC `posted_at`, `added_at`, and `last_seen_at`.
- `source_last_success_at` or a separate run ledger so cleanup knows whether a source completed.
- `status: active | stale | rejected` if soft deletion/history is needed.
- Add an ingestion schema version.

Recommended query indexes should be based on measured query plans, typically:

```text
(source, source_job_id) unique
(posted_at desc, _id asc)
(last_seen_at desc)
(work_type, posted_at desc)
(experience_level, posted_at desc)
saved_jobs: (user_id, saved_at desc, _id desc)
saved_jobs: unique (user_id, job_id)
company_logos: (company_key) unique
```

Do not add an index for every filter automatically. Verify with MongoDB explain plans and remove indexes that only slow writes.

#### `ingestion_runs`

Persist one record per worker run and one child status per source:

```text
run_id, started_at, finished_at, code_version,
source, status, fetched, accepted, rejected, upserted,
failed, duration_ms, error_class, error_message_redacted
```

Cleanup should use the last **successful** source run, not merely wall-clock age. This prevents a provider outage from deleting a healthy historical catalog.

### 5.4 API service rules

1. Use an app factory and lifespan-managed async clients.
2. Keep routes thin: validate DTO → call service → serialize response.
3. Make repositories own Mongo queries and projections.
4. Add explicit response models for jobs, saved jobs, resume results, and error envelopes.
5. Add request IDs, structured logs, latency metrics, and upstream timing.
6. Use Redis for distributed rate limits and short-lived filter/result caching when replicas are introduced.
7. Keep LLM calls behind one client/gateway with concurrency limits, timeouts, retries only for safe errors, and token budgets.
8. Add readiness (`/api/ready`) separately from liveness (`/api/health`).

### 5.5 Worker and source rules

Each provider adapter should implement the same interface:

```text
fetch(config, since, run_context) -> Iterable[RawListing]
```

The adapter may handle provider pagination, auth, retries, backoff, and provider-specific parsing. It must not decide canonical tech classification, language policy, enrichment, cleanup, or Mongo schema. The worker owns those rules.

Use bounded concurrency:

- Async HTTP or a bounded thread pool for I/O.
- One shared provider limiter per provider.
- One bounded CPU pool for enrichment.
- Batch validation/upserts with bounded memory.
- Per-source circuit breaking and a clear failure threshold.

Store provider configuration outside Python constants once the list changes often. A small `source_configs` collection or versioned YAML is enough; do not build an admin panel prematurely.

### 5.6 When to split further

Only split services when one of these is true:

- API latency is affected by ingestion or CPU enrichment despite separate processes.
- A provider requires independent credentials, deployment cadence, or network policy.
- Resume/chat workloads need separate autoscaling and budgets.
- Mongo write load and read load need independent scaling.

The likely sequence is API + worker → API + worker + Redis → separate AI worker or search index → only then provider-specific services if necessary.

## 6. File-by-file review matrix

The matrix below covers every tracked application/configuration/documentation file in the review scope. Generated caches, `.git`, `.venv`, and secret values in `.env` were intentionally excluded.

### Root and application bootstrap

| File | Role | Review result / risk |
|---|---|---|
| `main.py` | FastAPI assembly, CORS, health, lifespan | Good small bootstrap. Closes only the async Mongo client; health is liveness-only and CORS values are not trimmed. Add readiness and app factory. |
| `config/settings.py` | Environment-backed settings | Centralized, but all secrets are optional and failure occurs late. Validate required settings by runtime mode; normalize comma-separated origins. |
| `db/mongo.py` | Cached sync/async Mongo clients | Useful central module, but storage bypasses it. Add explicit timeouts, pool policy, ping/readiness, and one lifecycle owner per process. |
| `models/job.py` | Job, saved-job, logo Pydantic schemas | Stronger than untyped dictionaries and correctly models ObjectId/dates. Add bounds for skills/description and separate API DTOs from persistence models. |
| `ingest_api.py` | API-source CLI entrypoint | Correct thin entrypoint. `load_dotenv()` is redundant with settings but harmless; return non-zero status on failed run. |
| `ingest_scrapper.py` | Scraper-source CLI entrypoint | Same assessment as `ingest_api.py`. It should propagate structured runner failure to CI. |
| `requirements.txt` | Runtime dependencies | Pinned versions are better than ranges, but there is no lock/hash workflow and no dev/test tool declaration. Keep runtime and development dependencies separate. |
| `.env.example` | Configuration template | Does not expose secret values and lists the main settings. Add explicit required/optional notes and a production CORS example. |
| `.env` | Local secrets | Not read or printed. It is ignored correctly; rotate any credential if it was ever committed or shared. |
| `.gitignore` | Local/generated file exclusions | Correctly ignores `.env`, virtualenv, caches, `node_modules`, scratch, and local resumes. Confirm `docs/` and migration files remain tracked. |
| `.vscode/settings.json` | Local interpreter selection | Fine for local Windows development; it is not a deployment configuration. |
| `generate_audit_outputs.py` | Ad hoc static/query audit | Windows-specific `findstr` commands and live DB explain calls make it environment-dependent; the async client is not closed. Convert to a deliberate diagnostics CLI or remove after its findings are captured. |

### API, auth, AI, and parsing

| File | Role | Review result / risk |
|---|---|---|
| `fetch_api/auth.py` | Clerk JWKS and JWT verification | F-02/F-17: missing issuer/audience and blocking network I/O. Add typed verifier, cache TTL, async client, and claim tests. |
| `fetch_api/limiter.py` | SlowAPI key selection | Works conceptually for user/IP keys, but verification can happen before the route and again as a dependency; invalid bearer tokens can trigger auth work. Use distributed storage and a lightweight token key strategy where safe. |
| `fetch_api/jobs.py` | Search, matches, filter values, job detail | Good route coverage and escaped regex. F-16: large pages, expensive aggregations, uncached distinct values. The API directly imports ingestion enrichment/HTML functions. Add service/repository boundaries and response models. |
| `fetch_api/saved_jobs.py` | Authenticated saved-job CRUD | F-06/F-07/F-08 are concrete correctness issues. Add ObjectId dependency, unique index/upsert, cursor pagination, and stable response serialization. Avoid returning validation exception text. |
| `chatbot/chat_service.py` | Groq chat client and prompt | Has useful upstream error mapping. It creates a new `AsyncGroq` client per request, has no request budget here, and the system prompt contains product facts that can drift from the database. Manage client lifespan and centralize product facts. |
| `chatbot/router.py` | Chat request route | F-09: mutable-style default declaration, unbounded `history`, no route rate limit, and no response model. Use `Field(default_factory=list)` plus character/count bounds. |
| `parsing/resume_parser.py` | PDF/DOCX extraction and Groq parsing | F-10/F-11: schema constant unused, output unchecked, full content already in memory. Add result model, bounded extraction, safer errors, and an LLM gateway. |
| `parsing/resume.py` | Resume upload route | F-09/F-10: optional metadata size check and no body limit/content signature validation. Add streaming enforcement, route limits, and response model. |
| `fetch_api/__init__.py` | Package marker | Empty and harmless. |
| `chatbot/__init__.py` | Package marker | Empty and harmless. |
| `parsing/__init__.py` | Package marker | Empty and harmless. |

### Ingestion runners

| File | Role | Review result / risk |
|---|---|---|
| `listings/run_api.py` | Concurrent API-source orchestration | F-03/F-25: swallowed source errors and duplicated runner infrastructure. Shared process pool is a good direction, but source results must be returned and persisted. |
| `listings/run_scrapper.py` | Concurrent scraper orchestration | F-03/F-12/F-25: no shared CPU executor, duplicated runner code, and LinkedIn is commented out rather than represented as a disabled source with health state. |
| `listings/__init__.py` | Package marker | Empty and harmless. |
| `listings/scraping/__init__.py` | Package marker | Empty and harmless. Some nested folders use namespace-package behavior instead of explicit markers; standardize packaging if distributing a wheel/container. |

### API-based provider adapters

| File | Role | Review result / risk |
|---|---|---|
| `listings/greenhouse/fetcher.py` | Greenhouse company-board ingestion | Uses shared processing and bounded company concurrency. Hard-coded catalog, swallowed per-company failures, and direct indexing of provider fields can silently drop a company. |
| `listings/lever/fetcher.py` | Lever ingestion | Uses shared processing and flags missing posted date. Hard-coded catalog; the many unused enrichment imports make the contract harder to read. |
| `listings/ashby/fetcher.py` | Ashby ingestion | Uses shared processing. Date parsing and provider schema assumptions can fail per company; missing IDs become weak identifiers. |
| `listings/remoteok/fetcher.py` | RemoteOK ingestion | Simple and bounded. Missing company/source IDs can collapse records into the same upsert key; provider response shape should be contract-tested. |
| `listings/himalayas/fetcher.py` | Paginated Himalayas ingestion | Has retries and a shared processing handoff. F-21: queues all offsets and cancellation is ineffective; page ordering assumptions should be explicit. |
| `listings/adzuna/fetcher.py` | Multi-country/query Adzuna ingestion | Has retry/backoff and a raw cap, but F-15/F-21 apply. The free-tier limiter must be global, and the full task list should not be submitted up front. |
| `listings/adzuna/fetcher_test.py` | Manual Adzuna performance variant | Not a real test: it duplicates production logic, uses live calls, mutates global in-flight state, and has no assertions. Replace with mocked response tests. |

### Scraper/provider adapters

| File | Role | Review result / risk |
|---|---|---|
| `listings/hackernews/fetcher.py` | HN “Who is hiring” ingestion | Sequential network calls, swallowed comment failures, inline enrichment/filtering, and no shared source result contract. Preserve provider parsing but move processing to the worker. |
| `listings/scraping/weworkremotely/fetcher.py` | WWR RSS ingestion | Correctly handles RSS date parsing and age filtering locally, but bypasses the shared pipeline and has no company domain. Add parser fixtures and centralize enrichment. |
| `listings/scraping/workday/fetcher.py` | Workday API scraping | F-12/F-14: inline enrichment and duplicate description key. Hard-coded endpoints are fragile; each company's response should have a contract fixture. |
| `listings/scraping/linkedin/fetcher.py` | LinkedIn guest scraping | Disabled in the runner, but F-13 makes the code unsafe to re-enable. Also has aggressive scraping/rate-limit risk and should remain isolated behind a feature flag and source health policy. |

### Shared ingestion implementation

| File | Role | Review result / risk |
|---|---|---|
| `listings/shared/pipeline.py` | CPU enrichment and filtering | Good reusable shape and small-batch fallback. Its `process_single_job()` annotation says it can return `None` but it returns a dict; filtered records are returned with a marker. Make the contract typed and immutable where possible. |
| `listings/shared/storage.py` | Sync Mongo persistence, cleanup, indexes | Highest-risk file: F-01/F-04/F-05/F-19/F-20/F-22. It also contains unused/dead link-checking functions and a separate client singleton. Split persistence, freshness, validation, and maintenance responsibilities. |
| `listings/shared/enrich.py` | Regex-based skills/work/experience enrichment | Useful centralized vocabulary and deterministic behavior. The large global regex is expensive to compile and maintain; add fixtures for false positives and vocabulary versioning. |
| `listings/shared/normalize.py` | HTML/text normalization | Small and reusable. `strip_html()` intentionally summarizes content, so document that it is not a lossless sanitizer; add malformed HTML/entity fixtures. |
| `listings/shared/tech_filter.py` | Tech whitelist/blacklist | Fast deterministic filter, but title/first-500-description heuristics can create false positives/negatives. Track filter reason and periodically review samples. |
| `listings/shared/logos.py` | Clearbit logo lookup/cache | External HEAD requests are parallelized and cached. Add provider timeout/budget metrics, avoid repeated negative lookups if appropriate, and do not make logo lookup able to fail ingestion. |
| `listings/shared/__init__.py` | Package marker | Empty and harmless. |

### Maintenance and operational scripts

| File | Role | Review result / risk |
|---|---|---|
| `pipeline/audit_indexes.py` | Index inspection utility | Uses a machine-specific `sys.path`, has unused imports, and does not close the client. Make it environment-independent and include query usage stats only when explicitly requested. |
| `pipeline/backfill_enrichment.py` | Full enrichment backfill | Uses the central async-service DB helper's sync client but builds all `UpdateOne` operations in memory. Batch writes, add dry-run/version filters, and close the client. |
| `pipeline/backfill_fingerprints.py` | Fingerprint migration | Batches writes and closes the client, which is good. It updates every eligible document; add a `missing`/version filter and migration log. |
| `pipeline/cleanup.py` | Manual expiry/stats runner | Thin and useful, but inherits F-01/F-20. It should use the same run-aware cleanup service as scheduled ingestion. |
| `pipeline/fix_duplicate_skills.py` | One-time description cleanup | Batches only at the end, so memory grows with collection size. Add bounded batches, a migration marker, and tests for regex edge cases. |
| `scratch/cleanup.py` | Experimental non-English cleanup | Unsafe to run: loads the entire collection and uses `{'': chunk}` instead of an `_id` filter. Keep it untracked/removed from operational instructions; never use it as a cleanup path. |
| `pipeline/__init__.py` | Package marker | Empty and harmless. |

### CI, tests, and documentation

| File/folder | Role | Review result / risk |
|---|---|---|
| `.github/workflows/ingestion.yml` | Scheduled two-stage ingestion | Uses pinned Python version and concurrency, which is good. It has no lint/tests/artifacts and trusts runners to report success even when source errors are swallowed. The two stages each run cleanup, causing repeated maintenance work. |
| `tests/fixtures/.gitkeep` | Test fixture placeholder | Confirms no actual fixture suite exists. Populate with small provider payloads, not production secrets or large resumes. |
| `test_rate_limit.py` | Live endpoint smoke script | Requires a manually running server, prints rather than asserts, and is not suitable as CI validation. |
| `test_rate_limit_auth.py` | Auth/rate-limit smoke script | Uses mocks but has no assertions and can still depend on the database through the route. Convert to isolated tests. |
| `docs/AUDIT.md` | Existing broad audit | Useful inventory, but stale: it says `models/` was removed even though `models/job.py` exists, and it describes several fixes as complete while the findings in this document remain present. Do not treat it as current source of truth. |
| `docs/AUDIT_DATA_POINTS.md` | Schema/data reference | Helpful field inventory, but its “cross-source dedup” fingerprint description conflicts with the source-dependent implementation. Its claim that schema/date/cleanup behavior is verified should be rechecked after code fixes. |
| `docs/INGESTION_ARCHITECTURE.md` | Intended ingestion design | Good description of the shared process-pool goal, but it is aspirational: four active/available adapters bypass the stated handoff. |
| `docs/SPEC.md` | Historical optimization/fix spec | Valuable history, not a current acceptance report. It states cleanup and bottleneck fixes are complete although cleanup date semantics and runner failure semantics still need work. |
| `docs/groq_api_limits.md` | Model/limit notes | Treat quotas as operational configuration that must be verified with the provider and monitored; the document is not enforced by code. |
| `doc/` | Empty documentation folder | Remove or consolidate in a future cleanup; not a runtime issue. |

## 7. Practical remediation roadmap

### Phase 0 — before the next production ingestion

1. Fix date normalization and cleanup to use timezone-aware datetimes and `last_seen_at`/successful-run semantics.
2. Make source failures visible and return a non-zero worker exit code when required thresholds fail.
3. Validate Clerk issuer and audience; move JWKS retrieval to a bounded cached client.
4. Validate saved-job IDs before any database operation; add the unique saved-job index after checking existing duplicates.
5. Enforce upload body size while reading and validate the resume result with Pydantic.
6. Add chat/resume rate limits, message/history limits, and LLM concurrency limits.
7. Remove the duplicate Workday description key and fix LinkedIn's datetime handling before any re-enable decision.
8. Stop running ad hoc/scratch cleanup scripts in operational workflows.

### Phase 1 — make behavior testable

1. Introduce `RawListing`, `ProcessedListing`, `SourceRunResult`, `ResumeResult`, and API response models.
2. Extract date, fingerprint, freshness, saved-job, and serialization helpers into small modules.
3. Add unit tests without network/database dependencies.
4. Add provider parser contract fixtures for representative success, empty, malformed, 404, rate-limit, and changed-schema responses.
5. Add a mocked Mongo integration suite for indexes, upserts, cleanup, and pagination.
6. Add CI steps: formatting, lint/type checks, unit tests, and a compile/import smoke test.

### Phase 2 — separate the worker boundary

1. Consolidate `run_api.py` and `run_scrapper.py` into one runner with source configuration.
2. Move all providers to fetch/map-only adapters and route every listing through the shared processing pipeline.
3. Persist `ingestion_runs` and source-level metrics.
4. Use one worker-owned sync Mongo client with explicit timeouts and bounded pools.
5. Add a Redis-backed distributed limiter before deploying multiple API workers.
6. Add short-TTL filter caching and review Mongo query plans under realistic data volume.

### Phase 3 — scale only where measurements justify it

1. Introduce a queue for independent source jobs if scheduled runs exceed the worker budget.
2. Isolate chat/resume into an AI worker if paid calls or CPU extraction compete with API latency.
3. Add a dedicated search index only if MongoDB text search cannot meet relevance/latency requirements.
4. Move provider catalogs to versioned configuration or a small admin-managed collection.
5. Add object storage and asynchronous document scanning if resume volume or retention changes.

## 8. Verification checklist for the next implementation pass

### Data and persistence

- [ ] All persisted date fields are native UTC BSON dates.
- [ ] A job seen in a successful run is not expired because it is old.
- [ ] A job is not expired after a failed or partial source run.
- [ ] String, datetime, missing, naive, and malformed provider dates have explicit tests.
- [ ] `(source, source_job_id)` is unique and malformed/missing provider IDs are quarantined.
- [ ] Cross-source duplicate detection is separately measurable and non-destructive.
- [ ] Schema rejection stores reason and run/source context.
- [ ] Saved-job uniqueness and pagination are tested.

### API and security

- [ ] Wrong issuer and audience tokens are rejected.
- [ ] JWKS refresh has TTL, timeout, locking, and a defined stale-cache policy.
- [ ] Health and readiness endpoints have distinct semantics.
- [ ] Public, chat, resume, and authenticated routes have distributed quotas.
- [ ] Query/page/history/upload budgets are enforced server-side.
- [ ] Error responses do not include raw validation/provider exception details.

### Ingestion and operations

- [ ] Every provider returns a structured status.
- [ ] A provider returning zero records is distinguishable from a provider failure.
- [ ] Cleanup is run once per complete ingestion plan, not once per stage by accident.
- [ ] All sources share one processing and validation contract.
- [ ] Provider rate limits are global per provider, not per worker.
- [ ] CI runs tests and fails on configured source/rejection thresholds.
- [ ] Each run emits a stable run ID and preserves enough metrics to diagnose it.

## 9. Review limitations

- This was a static review of the repository contents and existing documentation. No production database mutation, cleanup, migration, or ingestion run was performed.
- `.env` was intentionally not opened or printed; secret validity and production configuration were not assessed.
- Existing documents refer to live database counts and prior benchmarks, but those claims were not independently re-run as part of this code-only review.
- External provider behavior, current quotas, Clerk claim configuration, and MongoDB query plans should be verified in a controlled environment before applying migrations or changing concurrency.

## 10. Final recommendation

Keep the current product as a **modular monolith with a separately deployed ingestion worker**. Do not start with many microservices. First make the data lifecycle trustworthy, source failures observable, auth claims complete, expensive inputs bounded, and the provider contract uniform. Once those foundations are in place, MongoDB plus FastAPI should be sufficient for an early WHOFY launch; Redis, a queue, and a dedicated search/AI worker can be introduced incrementally when measurements show they are needed.
