from datetime import datetime
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from listings.shared.enrich import bake_required_skills, detect_experience, detect_work_type, extract_required_skills
from listings.shared.normalize import full_text, strip_html
from listings.shared.storage import save_jobs
from listings.shared.tech_filter import filter_tech_jobs

ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{company}"

from listings.shared.companies import load_companies
COMPANIES = load_companies("ashby")

HEADERS = {
    "User-Agent": "Whofy Job Aggregator (contact: whofyteam@gmail.com)"
}


def fetch_ashby_jobs(company: dict) -> list[dict]:
    url = ASHBY_API.format(company=company["slug"])
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
        title = job.get("title", "")
        location = job.get("location", "Not specified")
        if isinstance(location, dict):
            location = location.get("name", "Not specified")

        raw_description = job.get("descriptionHtml", "") or job.get("description", "")
        
        job_url = job.get("jobUrl", "")
        if not job_url:
            job_url = f"https://jobs.ashbyhq.com/{company['slug']}/{job.get('id', '')}"
            
        normalized.append({
            "source": "ashby",
            "source_job_id": f"ash_{job.get('id', '')}",
            "title": title,
            "company": company["name"],
            "company_domain": company.get("domain", ""),
            "location": location,
            "raw_description": raw_description,
            "apply_url": job_url,
            "posted_at": datetime.fromisoformat(job.get("publishedAt").replace("Z", "+00:00")) if job.get("publishedAt") else None,
        })

    return normalized


from listings.shared.pipeline import process_jobs_batch

def main(mp_executor=None):
    all_jobs = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_ashby_jobs, company): company for company in COMPANIES}
        for future in as_completed(futures):
            company = futures[future]
            print(f"Fetching jobs for {company['name']}...")
            try:
                jobs = future.result()
                all_jobs.extend(jobs)
            except Exception as e:
                print(f"Error processing {company['name']}: {e}")

    import time
    t_start = time.time()
    
    print(f"\nTotal jobs fetched: {len(all_jobs)}")

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
        result = save_jobs(accepted_jobs, source="ashby")
        result["tech_filtered"] = tech_filtered
        result["non_english_skipped"] = lang_filtered
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
