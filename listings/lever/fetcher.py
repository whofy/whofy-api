from datetime import datetime
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from listings.shared.enrich import bake_required_skills, detect_experience, detect_work_type, extract_required_skills
from listings.shared.normalize import extract_bullets, first_paragraph
from listings.shared.storage import save_jobs
from listings.shared.tech_filter import filter_tech_jobs

LEVER_API = "https://api.lever.co/v0/postings/{company}?mode=json"

from listings.shared.companies import load_companies
COMPANIES = load_companies("lever")

HEADERS = {
    "User-Agent": "Whofy Job Aggregator (contact: whofyteam@gmail.com)"
}

WORKPLACE_TYPE_MAP = {
    "on-site": "On-site",
    "onsite": "On-site",
    "remote": "Remote",
    "hybrid": "Hybrid",
}


def fetch_lever_jobs(company: dict) -> list[dict]:
    url = LEVER_API.format(company=company["slug"])
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Error fetching {company['name']}: {e}")
        return []

    raw_jobs = resp.json()
    if not raw_jobs:
        return []
    print(f"  -> {len(raw_jobs)} jobs found")

    normalized = []
    for job in raw_jobs:
        categories = job.get("categories", {})
        location = categories.get("location", "Not specified")

        description_plain = job.get("descriptionPlain", "")
        intro = first_paragraph(description_plain)
        lists = job.get("lists") or []
        first_bullets = extract_bullets(lists[0].get("content", "")) if lists else []
        description = "\n".join(([intro] if intro else []) + first_bullets)

        all_bullets = [b for lst in lists for b in extract_bullets(lst.get("content", ""), max_bullets=50)]
        detection_text = "\n".join([description_plain] + all_bullets)

        title = job.get("text", "")
        workplace_type = WORKPLACE_TYPE_MAP.get((categories.get("workplaceType") or "").lower())
        
        normalized.append({
            "source": "lever",
            "source_job_id": f"lv_{job['id']}",
            "title": title,
            "company": company["name"],
            "company_domain": company.get("domain", ""),
            "location": location,
            "description": description,
            "detection_text": detection_text,
            "apply_url": job.get("hostedUrl", ""),
            "posted_at": None,
            "data_quality_flags": ["missing_posted_at"],
            "work_type": workplace_type,
        })

    return normalized


from listings.shared.pipeline import process_jobs_batch

def main(mp_executor=None):
    all_jobs = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_lever_jobs, company): company for company in COMPANIES}
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
        result = save_jobs(accepted_jobs, source="lever")
        result["tech_filtered"] = tech_filtered
        result["non_english_skipped"] = lang_filtered
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
