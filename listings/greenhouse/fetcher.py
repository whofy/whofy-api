from datetime import datetime
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from listings.shared.enrich import bake_required_skills, detect_experience, detect_work_type, extract_required_skills
from listings.shared.normalize import full_text, strip_html
from listings.shared.storage import save_jobs
from listings.shared.tech_filter import filter_tech_jobs

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"

from listings.shared.companies import load_companies
COMPANIES = load_companies("greenhouse")

HEADERS = {
    "User-Agent": "Whofy Job Aggregator (contact: whofyteam@gmail.com)"
}


def fetch_greenhouse_jobs(company: dict) -> list[dict]:
    url = GREENHOUSE_API.format(board_token=company["board_token"])
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Error fetching {company['name']}: {e}")
        return []

    data = resp.json()
    raw_jobs = data.get("jobs", [])
    if not raw_jobs:
        return []
    print(f"  -> {len(raw_jobs)} jobs found")

    normalized = []
    for job in raw_jobs:
        location = job.get("location", {}).get("name", "Not specified")
        title = job.get("title", "")
        raw_content = job.get("content", "")
        normalized.append({
            "source": "greenhouse",
            "source_job_id": f"gh_{job['id']}",
            "title": title,
            "company": company["name"],
            "company_domain": company.get("domain", ""),
            "location": location,
            "raw_description": raw_content,
            "apply_url": job.get("absolute_url", ""),
            "posted_at": datetime.fromisoformat(job.get("updated_at").replace("Z", "+00:00")) if job.get("updated_at") else None,
        })

    return normalized

from listings.shared.pipeline import process_jobs_batch

def main(mp_executor=None):
    import time
    from listings.shared.storage import save_jobs
    
    t_start = time.time()
    all_jobs = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_greenhouse_jobs, company): company for company in COMPANIES}
        for future in as_completed(futures):
            company = futures[future]
            print(f"Fetching jobs for {company['name']}...")
            try:
                jobs = future.result()
                all_jobs.extend(jobs)
            except Exception as e:
                print(f"Error processing {company['name']}: {e}")

    t_fetch = time.time()
    print(f"\nTotal raw jobs fetched: {len(all_jobs)}")
    print(f"Total fetch time: {t_fetch - t_start:.2f}s")

    print("Running process_jobs_batch (enrichment + filtering)...")
    batch_result = process_jobs_batch(all_jobs, mp_executor=mp_executor)
    accepted_jobs = batch_result["accepted"]
    tech_filtered = batch_result["tech_filtered"]
    lang_filtered = batch_result["lang_filtered"]
    
    t_filter = time.time()
    print(f"After MP enrichment/filter: {len(accepted_jobs)} accepted")
    print(f"Filtered (Tech): {tech_filtered}")
    print(f"Filtered (Lang): {lang_filtered}")
    print(f"MP Pipeline time: {t_filter - t_fetch:.2f}s")

    if accepted_jobs:
        result = save_jobs(accepted_jobs, source="greenhouse")
        result["tech_filtered"] = tech_filtered
        result["non_english_skipped"] = lang_filtered
        t_save = time.time()
        print(f"Saved to MongoDB: {result}")
        print(f"Save jobs total time: {t_save - t_filter:.2f}s")
        print(f"TOTAL RUN TIME: {t_save - t_start:.2f}s")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
