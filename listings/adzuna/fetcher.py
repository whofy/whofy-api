import requests
from listings.shared.enrich import bake_required_skills, detect_experience, detect_work_type, extract_required_skills
from listings.shared.normalize import full_text, strip_html
from listings.shared.storage import save_jobs
from listings.shared.tech_filter import filter_tech_jobs
from config.settings import settings

ADZUNA_APP_ID = settings.adzuna_app_id
ADZUNA_APP_KEY = settings.adzuna_app_key
ADZUNA_API = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

COUNTRIES = ["in", "us", "gb", "ca", "au", "de"]

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
]

HEADERS = {
    "User-Agent": "Whofy Job Aggregator (contact: rohanakode12@gmail.com)"
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
        }

        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if resp.status_code == 400:
                break
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  Error fetching Adzuna ({country}) page {page}: {e}")
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


def main():
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("ADZUNA_APP_ID and ADZUNA_APP_KEY not set, skipping Adzuna.")
        return

    all_jobs = []
    seen_ids = set()

    for country in COUNTRIES:
        for query in SEARCH_QUERIES:
            print(f"Fetching Adzuna jobs ({country.upper()}, '{query}')...")
            jobs = fetch_adzuna_jobs(country, query, max_pages=5)
            for job in jobs:
                if job["source_job_id"] not in seen_ids:
                    seen_ids.add(job["source_job_id"])
                    all_jobs.append(job)
            print(f"  -> {len(jobs)} fetched, {len(all_jobs)} unique total")

            if len(all_jobs) >= 7000:
                break
        if len(all_jobs) >= 7000:
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
