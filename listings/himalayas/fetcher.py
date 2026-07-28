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
PAGE_SIZE = 10
MAX_AGE_DAYS = 30
PAGE_DELAY = 3
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


def _posted_at(job: dict) -> str:
    pub = job.get("pubDate")
    if not pub:
        return ""
    return datetime.fromtimestamp(int(pub), tz=timezone.utc).isoformat()


def fetch_himalayas_jobs() -> list[dict]:
    cutoff = _cutoff_ts()
    offset = 0
    all_jobs = []

    while True:
        try:
            data = _fetch_page(offset)
        except requests.RequestException as e:
            print(f"  Error fetching page at offset {offset}: {e}")
            break

        jobs = data.get("jobs", [])
        if not jobs:
            break

        hit_old = False
        for job in jobs:
            pub = job.get("pubDate")
            if pub and int(pub) < cutoff:
                hit_old = True
                break

            title = job.get("title", "")
            raw_desc = job.get("description", "")
            description = strip_html(raw_desc)
            detection_text = full_text(raw_desc)
            location = _location_from(job)
            required_skills = extract_required_skills(title, detection_text)

            all_jobs.append({
                "source": "himalayas",
                "source_job_id": f"hml_{job.get('guid', '')}",
                "title": title,
                "company": job.get("companyName", ""),
                "company_domain": "",
                "location": location,
                "description": bake_required_skills(description, required_skills),
                "apply_url": job.get("applicationLink", ""),
                "posted_at": _posted_at(job),
                "work_type": detect_work_type(title, location, detection_text),
                "experience_level": detect_experience(title, detection_text),
                "required_skills": required_skills,
            })

        if hit_old:
            break

        total = data.get("totalCount", 0)
        offset += PAGE_SIZE
        if offset >= total:
            break

        if offset % 5000 == 0:
            print(f"  ... fetched {len(all_jobs)} jobs so far (offset {offset})")

        time.sleep(PAGE_DELAY)

    return all_jobs


def main():
    print("Fetching jobs from Himalayas...")
    all_jobs = fetch_himalayas_jobs()
    print(f"Total jobs fetched (last {MAX_AGE_DAYS} days): {len(all_jobs)}")

    all_jobs = filter_tech_jobs(all_jobs)
    print(f"After tech filter: {len(all_jobs)}")

    if all_jobs:
        result = save_jobs(all_jobs, source="himalayas")
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
