import requests
from sources.shared.enrich import bake_required_skills, detect_experience, detect_work_type, extract_required_skills
from sources.shared.normalize import full_text, strip_html
from sources.shared.storage import save_jobs
from config.settings import settings

ADZUNA_APP_ID = settings.adzuna_app_id
ADZUNA_APP_KEY = settings.adzuna_app_key
ADZUNA_API = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

# Countries to search (Adzuna supports these)
COUNTRIES = ["in", "us", "gb"]

HEADERS = {
    "User-Agent": "Whofy Job Aggregator (contact: rohanakode12@gmail.com)"
}


def fetch_adzuna_jobs(country: str, max_pages: int = 5) -> list[dict]:
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
            # Adzuna's `what` param ANDs every word together — "software
            # developer intern fresher" as one query matches almost nothing
            # (verified: 1 total result for India). `what_or` matches ANY of
            # the words instead, which is what we actually want here.
            "what_or": "software developer intern fresher junior engineer",
        }

        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
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
    all_jobs = []

    for country in COUNTRIES:
        print(f"Fetching Adzuna jobs ({country.upper()})...")
        jobs = fetch_adzuna_jobs(country)
        print(f"  -> {len(jobs)} jobs found")
        all_jobs.extend(jobs)

    print(f"\nTotal jobs fetched: {len(all_jobs)}")

    if all_jobs:
        result = save_jobs(all_jobs, source="adzuna")
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save (set ADZUNA_APP_ID and ADZUNA_APP_KEY to enable).")


if __name__ == "__main__":
    main()
