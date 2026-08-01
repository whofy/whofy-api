import time

import requests
from listings.shared.enrich import bake_required_skills, detect_experience, detect_work_type, extract_required_skills
from listings.shared.normalize import full_text, strip_html
from listings.shared.storage import save_jobs
from listings.shared.tech_filter import filter_tech_jobs
from config.settings import settings

ADZUNA_APP_ID = settings.adzuna_app_id
ADZUNA_APP_KEY = settings.adzuna_app_key
ADZUNA_API = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

# Throttle to respect Adzuna's ~25 calls/minute free-tier limit.
REQUEST_DELAY = 1.0
MAX_RETRIES = 3
RAW_JOB_CAP = 12000

# Signals the daily quota is exhausted so main() can stop early instead of
# grinding through every remaining query with failed calls.
class RateLimitExhausted(Exception):
    pass

COUNTRIES = ["in", "us", "gb", "ca", "au", "de", "fr", "nl", "br", "sg", "nz", "pl"]

SEARCH_QUERIES = [
    "software engineer",
    "software developer",
    "frontend developer",
    "backend developer",
    "fullstack developer",
    "data engineer",
    "data scientist",
    "devops engineer",
    "cloud engineer",
    "machine learning engineer",
    "QA engineer",
    "mobile developer",
    "UI UX designer",
    "product manager",
    "cybersecurity analyst",
    "systems engineer",
    "web developer",
    "python developer",
    "java developer",
    "react developer",
    "golang developer",
    "rust developer",
    "iOS developer",
    "android developer",
    "site reliability engineer",
    "data analyst",
    "database administrator",
    "network engineer",
    "blockchain developer",
    "AI engineer",
    "MLOps engineer",
    "platform engineer",
    "cloud architect",
    "solutions architect",
    "infrastructure engineer",
    "security engineer",
    "embedded engineer",
    "firmware engineer",
    "technical lead",
    "engineering manager",
    "scrum master",
    "technical program manager",
    "data architect",
    "ETL developer",
    "automation engineer",
    "DevSecOps",
    "Kubernetes engineer",
    "AWS engineer",
    "Azure engineer",
    "SAP consultant",
    "Salesforce developer",
    "ServiceNow developer",
    "ERP developer",
    "business intelligence",
    "power BI developer",
    "tableau developer",
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
                backoff = REQUEST_DELAY * (2 ** attempt)
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

        time.sleep(REQUEST_DELAY)

        data = resp.json()
        results = data.get("results", [])
        if not results:
            break

        for job in results:
            location = job.get("location", {})
            location_str = ", ".join(location.get("area", [])) if location.get("area") else "Not specified"
            title = job.get("title", "")
            raw_description = job.get("description", "")
            description = strip_html(raw_description)
            detection_text = full_text(raw_description)
            required_skills = extract_required_skills(title, detection_text)

            all_jobs.append({
                "source": "adzuna",
                "source_job_id": f"adz_{job.get('id', '')}",
                "title": title,
                "company": job.get("company", {}).get("display_name", ""),
                "location": location_str,
                "description": bake_required_skills(description, required_skills),
                "apply_url": job.get("redirect_url", ""),
                "posted_at": job.get("created", ""),
                "work_type": detect_work_type(title, location_str, detection_text),
                "experience_level": detect_experience(title, detection_text),
                "required_skills": required_skills,
            })

    return all_jobs


def _fetch_wrapper(country, query):
    try:
        return fetch_adzuna_jobs(country, query, max_pages=3)
    except RateLimitExhausted:
        return None

def main():
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

    print(f"\nTotal unique jobs fetched: {len(all_jobs)}")

    all_jobs = filter_tech_jobs(all_jobs)
    print(f"After tech filter: {len(all_jobs)}")

    if all_jobs:
        result = save_jobs(all_jobs, source="adzuna")
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
