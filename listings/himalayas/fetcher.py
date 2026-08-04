import time
import requests
from datetime import datetime, timezone, timedelta

from listings.shared.enrich import (
    bake_required_skills, detect_experience, detect_work_type, extract_required_skills,
)
from listings.shared.normalize import full_text, strip_html
from listings.shared.storage import save_jobs
from listings.shared.tech_filter import filter_tech_jobs

API_URL = "https://himalayas.app/jobs/api"
PAGE_SIZE = 100
MAX_AGE_DAYS = 30
PAGE_DELAY = 1
MAX_RETRIES = 3

HEADERS = {
    "User-Agent": "Whofy Job Aggregator (contact: whofyteam@gmail.com)"
}


def _cutoff_ts() -> int:
    return int((datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).timestamp())


def _fetch_page(offset: int) -> dict:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                API_URL,
                params={"limit": PAGE_SIZE, "offset": offset},
                headers=HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt < MAX_RETRIES:
                wait = attempt * 5
                print(f"  Retry {attempt}/{MAX_RETRIES} for offset {offset} (waiting {wait}s): {e}")
                time.sleep(wait)
            else:
                raise


def _location_from(job: dict) -> str:
    restrictions = job.get("locationRestrictions") or []
    if restrictions:
        return ", ".join(restrictions)
    return "Remote"


def _posted_at(job: dict):
    pub = job.get("pubDate")
    if not pub:
        return None
    return datetime.fromtimestamp(int(pub), tz=timezone.utc)


def fetch_himalayas_jobs() -> list[dict]:
    cutoff = _cutoff_ts()
    all_jobs = []

    try:
        first_page = _fetch_page(0)
    except requests.RequestException as e:
        print(f"  Error fetching initial page: {e}")
        return []

    jobs = first_page.get("jobs", [])
    total = first_page.get("totalCount", 0)

    def _process_jobs(jobs_list):
        processed = []
        hit_old = False
        for job in jobs_list:
            pub = job.get("pubDate")
            if pub and int(pub) < cutoff:
                hit_old = True
                break

            title = job.get("title", "")
            raw_desc = job.get("description", "")
            location = _location_from(job)
            processed.append({
                "source": "himalayas",
                "source_job_id": f"hml_{job.get('guid', '')}",
                "title": title,
                "company": job.get("companyName", ""),
                "company_domain": "",
                "location": location,
                "raw_description": raw_desc,
                "apply_url": job.get("applicationLink", ""),
                "posted_at": _posted_at(job),
            })
        return processed, hit_old

    first_processed, first_hit_old = _process_jobs(jobs)
    all_jobs.extend(first_processed)

    if first_hit_old or total <= PAGE_SIZE:
        return all_jobs

    from concurrent.futures import ThreadPoolExecutor, as_completed

    offsets = list(range(PAGE_SIZE, total, PAGE_SIZE))
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_offset = {executor.submit(_fetch_page, offset): offset for offset in offsets}
        
        for future in as_completed(future_to_offset):
            offset = future_to_offset[future]
            try:
                data = future.result()
            except requests.RequestException as e:
                print(f"  Error fetching page at offset {offset}: {e}")
                continue

            page_jobs = data.get("jobs", [])
            if not page_jobs:
                continue

            processed, hit_old = _process_jobs(page_jobs)
            all_jobs.extend(processed)

            if len(all_jobs) % 5000 < PAGE_SIZE * 4: # roughly log every 5000
                print(f"  ... fetched ~{len(all_jobs)} jobs so far")

            if hit_old:
                # Can't cleanly cancel all futures, but we stop processing results
                executor.shutdown(wait=False, cancel_futures=True)
                break

    return all_jobs

BATCH_SIZE = 2000

from listings.shared.pipeline import process_jobs_batch

def main(mp_executor=None):
    import time
    t_start = time.time()
    
    print("Fetching jobs from Himalayas...")
    all_jobs = fetch_himalayas_jobs()
    print(f"Total jobs fetched (last {MAX_AGE_DAYS} days): {len(all_jobs)}")

    print("Running process_jobs_batch (enrichment + filtering)...")
    batch_result = process_jobs_batch(all_jobs, mp_executor=mp_executor)
    accepted_jobs = batch_result["accepted"]
    tech_filtered = batch_result["tech_filtered"]
    lang_filtered = batch_result["lang_filtered"]
    
    t_filter = time.time()
    print(f"After MP enrichment/filter: {len(accepted_jobs)} accepted")
    print(f"Filtered (Tech): {tech_filtered}")
    print(f"Filtered (Lang): {lang_filtered}")

    if not accepted_jobs:
        print("No jobs to save.")
        return

    for i in range(0, len(accepted_jobs), BATCH_SIZE):
        batch = accepted_jobs[i:i + BATCH_SIZE]
        result = save_jobs(batch, source="himalayas")
        if i == 0:
            result["tech_filtered"] = tech_filtered
            result["non_english_skipped"] = lang_filtered
        print(f"Saved batch {i // BATCH_SIZE + 1} ({len(batch)} jobs): {result}")

if __name__ == "__main__":
    main()
