import re
import time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from listings.shared.pipeline import process_jobs_batch
from listings.shared.storage import save_jobs

MAX_AGE_DAYS = 30
PAGE_SIZE = 20
MAX_JOBS_PER_COMPANY = 1000

from listings.shared.companies import load_companies
COMPANIES = load_companies("workday")

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Whofy Job Aggregator (contact: whofyteam@gmail.com)",
}


def _parse_posted_age(posted_on: str) -> int | None:
    if not posted_on:
        return None
    m = re.search(r"(\d+)\s*Day", posted_on, re.IGNORECASE)
    if m:
        return int(m.group(1))
    if "today" in posted_on.lower() or "just posted" in posted_on.lower():
        return 0
    if "yesterday" in posted_on.lower():
        return 1
    if "30+" in posted_on:
        return 31
    return None


def _posted_at_from_age(days_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.isoformat()


def fetch_workday_jobs(company: dict) -> list[dict]:
    jobs_url = company["jobs_url"]
    detail_base = company["detail_base"]
    apply_base = company["apply_base"]

    all_listings = []
    offset = 0

    while offset < MAX_JOBS_PER_COMPANY:
        try:
            resp = requests.post(
                jobs_url,
                json={"limit": PAGE_SIZE, "offset": offset, "searchText": ""},
                headers=HEADERS,
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"  HTTP {resp.status_code} at offset {offset}, stopping")
                break
            data = resp.json()
        except Exception as e:
            print(f"  Error fetching {company['name']} at offset {offset}: {e}")
            break

        postings = data.get("jobPostings", [])
        if not postings:
            break

        total = data.get("total", 0)

        for job in postings:
            posted_on = job.get("postedOn", "")
            days_ago = _parse_posted_age(posted_on)

            if days_ago is not None and days_ago > MAX_AGE_DAYS:
                continue

            title = job.get("title", "")
            location = job.get("locationsText", "Not specified")
            external_path = job.get("externalPath", "")
            apply_url = f"{apply_base}{external_path}" if external_path else ""
            posted_at = _posted_at_from_age(days_ago) if days_ago is not None else ""

            slug = external_path.rstrip("/").rsplit("/", 1)[-1] if external_path else ""
            source_id = f"wd_{company['name'].lower().replace(' ', '')}_{slug}"

            all_listings.append({
                "title": title,
                "location": location,
                "apply_url": apply_url,
                "posted_at": posted_at,
                "description": None,
                "data_quality_flags": ["missing_description"],
                "external_path": external_path,
                "source_id": source_id,
            })

        offset += PAGE_SIZE
        if offset >= total:
            break
        time.sleep(0.5)

    if not all_listings:
        return []

    print(f"  -> {len(all_listings)} listings (within {MAX_AGE_DAYS} days)")

    # Return raw jobs — process_jobs_batch handles enrichment via the shared pipeline.
    # Workday's search API doesn't return descriptions; detection_text = title + location
    # preserves the current behavior of using location as a signal for skill/work-type detection.
    normalized = []
    for listing in all_listings:
        title = listing["title"]
        location = listing["location"]
        normalized.append({
            "source": "workday",
            "source_job_id": listing["source_id"],
            "title": title,
            "company": company["name"],
            "company_domain": company.get("domain", ""),
            "location": location,
            "raw_description": "",  # Workday API omits descriptions
            "detection_text": f"{title} {location}",
            "apply_url": listing["apply_url"],
            "posted_at": listing["posted_at"],
        })

    return normalized


def main(mp_executor=None):
    all_jobs = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_workday_jobs, company): company for company in COMPANIES}
        for future in as_completed(futures):
            company = futures[future]
            print(f"Fetching jobs for {company['name']}...")
            try:
                jobs = future.result()
                all_jobs.extend(jobs)
            except Exception as e:
                print(f"  ERROR for {company['name']}: {e}")

    print(f"\nTotal jobs fetched: {len(all_jobs)}")

    print("Running process_jobs_batch (enrichment + filtering)...")
    batch_result = process_jobs_batch(all_jobs, mp_executor=mp_executor)
    accepted_jobs = batch_result["accepted"]
    tech_filtered = batch_result["tech_filtered"]
    lang_filtered = batch_result["lang_filtered"]
    print(f"After MP enrichment/filter: {len(accepted_jobs)} accepted")
    print(f"Filtered (Tech): {tech_filtered}")
    print(f"Filtered (Lang): {lang_filtered}")

    if accepted_jobs:
        result = save_jobs(accepted_jobs, source="workday")
        result["tech_filtered"] = tech_filtered
        result["non_english_skipped"] = lang_filtered
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
