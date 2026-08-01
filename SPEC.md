# Whofy API Optimization and Fixes Spec

## 1. CI/CD Fix (Priority 0)
- **Problem**: The GitHub Actions daily ingestion workflow (`ingestion.yml`) was trying to run `listings/run_all.py`, which was deleted. This caused the workflow to fail.
- **Solution**: Split the ingestion step into two sequential steps: `python ingest_api.py` (which runs `listings/run_api.py`) and `python ingest_scrapper.py` (which runs `listings/run_scrapper.py`). 
- **Secret Management**: Confirmed `GROQ_API_KEY` is not required for ingestion, avoiding unnecessary secrets in the CI environment.

## 2. Ingestion Cleanup Bottleneck (Priority 1)
- **Problem**: `cleanup_non_english_jobs()` iterated through all 46,680+ documents in the database *every* ingestion run, running `langdetect` sequentially, and deleting documents one-by-one. This took nearly 4 minutes (~235s).
- **Solution**: 
  - **Batching & Multi-processing**: Rewrote the function to use `ProcessPoolExecutor` across 8 cores to parallelize the CPU-bound language detection, combined with `delete_many` chunking. This dropped the time to **~65s**.
  - **Flagging (Option B)**: Introduced a `lang_checked` boolean flag. `save_jobs()` now sets this flag during upsert. The cleanup function now only queries `{"lang_checked": {"$ne": True}}` and updates the checked status in bulk (`update_many`).
  - **Result**: Cleanup time dropped from 4 minutes to **0.07 seconds** when documents are already checked.

## 3. Database Verification (Priority 2)
- **Problem**: Uncertainty regarding live database state (indexes, orphans, document counts).
- **Solution**: 
  - Verified live document counts (`jobs: 46680`, `saved_jobs: 8`, `company_logos: 9196`).
  - Identified 3 orphaned indexes: `location_1`, `company_1`, and `posted_at_-1` (which is redundant due to `posted_at_-1__id_1`).

## 4. Codebase & Dependencies Cleanup (Priority 3)
- **Environment**: Removed unused `GEMINI_API_KEY`, `JWT_SECRET`, and Google OAuth secrets from `.env.example`. Added `GROQ_API_KEY` and `CLERK_SECRET_KEY`.
- **Node Modules**: Removed 66MB of accidental `node_modules/` from the Python backend and added it to `.gitignore`.
- **Dead Code**: Deleted vestigial folders `matching/`, `sources/`, `models/`, and `config/sources.py`.
- **Pipeline Scripts**: Fixed critical typos (`mongDB` -> `db`) in `pipeline/backfill_enrichment.py` and `pipeline/fix_duplicate_skills.py`. Successfully ran backfill on 13,000+ jobs.
- **Dependencies**: Removed unused packages `python-jose`, `authlib`, and `httpx` from `requirements.txt` and the virtual environment. Confirmed server health via `/api/health`.

## 5. Fetcher Benchmarking
- Added exact `time.time()` tracking to both `run_api.py` and `run_scrapper.py` `run_source_concurrently` wrappers.
- The end-to-end ingestion logs will now cleanly print `[Source_Name] Completed in X.XX seconds` to pinpoint which specific API/scraper is consuming the remaining 53 minutes of the 1-hour GitHub Action run.
