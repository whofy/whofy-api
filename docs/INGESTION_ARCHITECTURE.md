# Whofy Ingestion Architecture

## 1. Overview
The Whofy ingestion pipeline is responsible for gathering job listings from multiple platforms, filtering them to ensure they are tech-related and in English, enriching them (extracting skills, detecting work type and experience level), and saving them into MongoDB. The process is split into two primary entry points in CI/CD: `ingest_api.py` (which runs all API-based sources concurrently via `listings/run_api.py`) and `ingest_scrapper.py` (which runs traditional scraper-based sources via `listings/run_scrapper.py`).

## 2. The Core Problem This Architecture Solves
Early versions of this pipeline used a standard `ThreadPoolExecutor` to run concurrent source fetching and processing. However, because our enrichment steps (`extract_required_skills`, `detect_work_type`, etc.) rely heavily on CPU-bound regex searches across massive strings, running them inside thread pools caused severe Python Global Interpreter Lock (GIL) contention. 

In a real-world test, the Greenhouse fetcher originally took **1269 seconds** just to enrich and process 22,700 jobs. By decoupling the I/O-bound fetching from the CPU-bound enrichment and moving the latter to a multi-process `ProcessPoolExecutor`, Greenhouse's processing time plummeted to **273 seconds**—even while actively sharing the process pool with 5 other fetchers simultaneously! It is critical that CPU-bound parsing never runs inside the main fetch loop or a simple thread pool again.

## 3. The Standard Pattern for Any Source
Every source fetcher (e.g., `listings/greenhouse/fetcher.py`) MUST adhere to a strict division of responsibilities:
- **What a fetcher's job IS:** Execute network I/O (`requests.get`), handle pagination/authentication, and map the raw JSON into standard, unenriched job dictionaries.
- **What a fetcher's job is NOT:** It must **never** run enrichment methods (`extract_required_skills`, `detect_work_type`, `detect_experience`, `langdetect`) inline during the fetch loop. 
- **The Shared Process Pool:** Once a fetcher collects a list of raw job dicts, it hands them off to `process_jobs_batch(jobs, mp_executor=mp_executor)`. The `mp_executor` is a single shared `ProcessPoolExecutor` created once in `run_api.py` and passed down to every source's `main(mp_executor=None)` function. This prevents process explosion on constrained environments like GitHub Actions.
- **The Small-Batch Fallback:** In `listings/shared/pipeline.py`, there is an explicit check: `if len(jobs) < 300:`. If the batch is small, it processes synchronously. Pickling objects across process boundaries has overhead (a measured regression showed 26 jobs taking 3.1s in MP vs 0.1s synchronously).
- **The Core Handoff:**
  ```python
  from listings.shared.pipeline import process_jobs_batch

  def main(mp_executor=None):
      raw_jobs = fetch_my_source_jobs()
      batch_result = process_jobs_batch(raw_jobs, mp_executor=mp_executor)
      accepted_jobs = batch_result["accepted"]
      
      if accepted_jobs:
          save_jobs(accepted_jobs, source="mysource")
  ```

## 4. Step-by-Step: Adding a New Source
To add a new job source, follow these steps exactly:
1. **Create the file:** Create `listings/<new_source>/fetcher.py`.
2. **Implement fetch-only logic:** Keep network requests isolated and ensure pagination is handled.
3. **Map to Raw Schema:** Return dictionaries containing: `source`, `source_job_id`, `title`, `company`, `location`, `raw_description` (or `description` and `detection_text` if pre-formatted), `apply_url`, and `posted_at`.
4. **Wire into Pipeline:** Import and call `process_jobs_batch(raw_jobs, mp_executor=mp_executor)` in the `main` function as shown above.
5. **Register:** Add the `main` function to `listings/run_api.py` (or `run_scrapper.py`).
6. **Rate Limiting:** If the API has documented rate limits, implement backoff/sleep logic inline during the fetch (see Adzuna's implementation).
7. **Indexing:** Update `ensure_indexes()` in `listings/shared/storage.py` if new query patterns are introduced.
8. **Verification:** Before deploying, run a correctness check (comparing old sync output vs new MP output on ~20-30 real jobs), verify the Mongo stats dict (`upserted`, `modified`, `tech_filtered`), and confirm ingestion time hasn't regressed.

## 5. Known Bottlenecks & Accepted Tradeoffs
- **Adzuna Network Rate Limits:** The Adzuna fetcher takes ~570s (nearly 9.5 minutes) because it deliberately sleeps and throttles to respect the provider's free-tier API limits across thousands of queries. This is an **accepted, understood cost**. If it needs optimization later, levers include reducing the 12-country scope, reducing the 57 queries, or requesting higher rate limits.
- **LinkedIn Paused:** Scraping LinkedIn is currently paused/deferred due to aggressive blocking and is not part of this optimized pipeline.

## 6. Related Files Reference Table
| File Path | Purpose |
| :--- | :--- |
| `listings/run_api.py` | Entry point orchestrating all API fetchers, injects the shared `ProcessPoolExecutor`. |
| `listings/run_scrapper.py` | Entry point for traditional web scraping sources. |
| `listings/shared/pipeline.py` | Core MP logic; houses `process_jobs_batch` and small-batch fallback handling. |
| `listings/shared/storage.py` | MongoDB interactions, deduplication (`save_jobs`), and bulk writes. |
| `listings/shared/enrich.py` | Regex-heavy, CPU-bound extraction logic (skills, work type, experience). |
| `listings/greenhouse/fetcher.py` | The reference implementation for an optimized API source fetcher. |

## 7. CI/CD Notes
- **Timeout Configuration:** `.github/workflows/ingestion.yml` has `timeout-minutes: 60`. Given the current total pipeline time is ~9.5 minutes, this provides a massive safety buffer for network retries and transient slow-downs.
- **Dynamic Sizing:** GitHub Actions runners generally provide 2-vCPU environments. The shared `ProcessPoolExecutor` in `listings/shared/pipeline.py` is dynamically sized using `min(16, max(2, os.cpu_count() or 2))`. This ensures the pipeline gracefully scales down to 2 concurrent workers in CI without oversubscribing cores, while utilizing up to 16 workers on local development machines. Hardcoding worker counts will break this portability.
