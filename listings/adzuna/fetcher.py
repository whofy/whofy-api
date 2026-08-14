from datetime import datetime
import time

import requests
from listings.shared.rate_limiter import TokenBucket
from listings.shared.storage import save_jobs
from config.settings import settings

ADZUNA_APP_ID = settings.adzuna_app_id
ADZUNA_APP_KEY = settings.adzuna_app_key
ADZUNA_API = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

# Adzuna free tier is ~25 calls/minute = ~0.42/sec. Shared across all worker
# threads so the actual global rate matches the quota, regardless of how many
# threads are running.
MAX_RETRIES = 3
RAW_JOB_CAP = 12000
_BUCKET = TokenBucket(rate=0.4)

# Signals the daily quota is exhausted so main() can stop early instead of
# grinding through every remaining query with failed calls.
class RateLimitExhausted(Exception):
    pass

COUNTRIES = ["in", "us", "gb", "ca", "au", "de", "fr", "nl", "br", "sg", "nz", "pl"]

SEARCH_QUERIES = [
    "software engineer",
    "frontend developer",
    "backend developer",
    "fullstack developer",
    "data engineer",
    "data scientist",
    "machine learning engineer",
    "devops engineer",
    "mobile developer",
    "security engineer",
    "site reliability engineer",
    "product manager",
    "UI UX designer",
    "engineering manager",
    "QA engineer",
]

HEADERS = {
    "User-Agent": "Whofy Job Aggregator (contact: whofyteam@gmail.com)"
}


def fetch_adzuna_jobs(country: str, query: str, max_pages: int = 10) -> list[dict]:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("  ADZUNA_APP_ID and ADZUNA_APP_KEY not set, skipping")
        return []

    all_jobs = []

    for page in range(1, max_pages + 1):
        url = ADZUNA_API.format(country=country, page=page)
        params = {
            "app_id": ADZUNA_APP_ID,
            "app_key": ADZUNA_APP_KEY,
            "results_per_page": 50,
            "what": query,
            "category": "it-jobs",
            "sort_by": "date",
        }

        resp = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                _BUCKET.acquire()
                resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
            except requests.RequestException as e:
                print(f"  Error fetching Adzuna ({country}) page {page}: {e}")
                resp = None
                break

            # 429 = explicit rate limit; 503/500/502/504 = Adzuna throttling or
            # a transient server hiccup. Both get retried with backoff.
            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt == MAX_RETRIES:
                    print(f"  Adzuna ({country}) page {page} still failing (HTTP {resp.status_code}) after {MAX_RETRIES} retries — quota/throttle likely exhausted.")
                    raise RateLimitExhausted()
                backoff = 2 ** attempt
                print(f"  HTTP {resp.status_code} ({country}, page {page}), retry {attempt}/{MAX_RETRIES} in {backoff:.0f}s...")
                time.sleep(backoff)
                continue

            break

        if resp is None:
            break
        if resp.status_code == 400:
            break
        if resp.status_code != 200:
            print(f"  Error fetching Adzuna ({country}) page {page}: HTTP {resp.status_code}")
            break

        data = resp.json()
        results = data.get("results", [])
        if not results:
            break

        for job in results:
            location = job.get("location", {})
            location_str = ", ".join(location.get("area", [])) if location.get("area") else "Not specified"
            title = job.get("title", "")
            raw_description = job.get("description", "")
            all_jobs.append({
                "source": "adzuna",
                "source_job_id": f"adz_{job.get('id', '')}",
                "title": title,
                "company": job.get("company", {}).get("display_name", ""),
                "location": location_str,
                "raw_description": raw_description,
                "apply_url": job.get("redirect_url", ""),
                "posted_at": datetime.fromisoformat(job.get("created").replace("Z", "+00:00")) if job.get("created") else None,
            })

    return all_jobs


def _fetch_wrapper(country, query):
    try:
        return fetch_adzuna_jobs(country, query, max_pages=1)
    except RateLimitExhausted:
        return None

from listings.shared.pipeline import process_jobs_batch

def main(mp_executor=None):
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("ADZUNA_APP_ID and ADZUNA_APP_KEY not set, skipping Adzuna.")
        return

    all_jobs = []
    seen_ids = set()
    rate_limited = False

    from concurrent.futures import ThreadPoolExecutor, as_completed

    tasks = []
    for country in COUNTRIES:
        for query in SEARCH_QUERIES:
            tasks.append((country, query))

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_task = {executor.submit(_fetch_wrapper, c, q): (c, q) for c, q in tasks}
        
        for future in as_completed(future_to_task):
            c, q = future_to_task[future]
            try:
                jobs = future.result()
            except Exception as e:
                print(f"  Error fetching Adzuna jobs ({c.upper()}, '{q}'): {e}")
                continue

            if jobs is None:
                print("  Stopping early — saving what we have so far. The 24h scheduler will top up next run.")
                # Drop the queued (country, query) tasks. Without this, the
                # `with` block's shutdown(wait=True) still runs every one of
                # them — each burning 2s+4s+8s of retry backoff against a
                # quota we already know is dead.
                executor.shutdown(wait=False, cancel_futures=True)
                break

            print(f"Fetched Adzuna jobs ({c.upper()}, '{q}') -> {len(jobs)} jobs")
            for job in jobs:
                if job["source_job_id"] not in seen_ids:
                    seen_ids.add(job["source_job_id"])
                    all_jobs.append(job)

            if len(all_jobs) >= RAW_JOB_CAP:
                executor.shutdown(wait=False, cancel_futures=True)
                break

    import time
    t_start = time.time()
    
    print(f"\nTotal unique jobs fetched: {len(all_jobs)}")

    print("Running process_jobs_batch (enrichment + filtering)...")
    batch_result = process_jobs_batch(all_jobs, mp_executor=mp_executor)
    accepted_jobs = batch_result["accepted"]
    tech_filtered = batch_result["tech_filtered"]
    lang_filtered = batch_result["lang_filtered"]
    
    t_filter = time.time()
    print(f"After MP enrichment/filter: {len(accepted_jobs)} accepted")
    print(f"Filtered (Tech): {tech_filtered}")
    print(f"Filtered (Lang): {lang_filtered}")

    if accepted_jobs:
        result = save_jobs(accepted_jobs, source="adzuna")
        result["tech_filtered"] = tech_filtered
        result["non_english_skipped"] = lang_filtered
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
