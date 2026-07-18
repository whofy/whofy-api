import os
import requests
from sources.shared.enrich import bake_required_skills, detect_experience, detect_work_type, extract_required_skills
from sources.shared.storage import save_jobs

JOOBLE_API_KEY = os.environ.get("JOOBLE_API_KEY")
JOOBLE_API = "https://jooble.org/api/{api_key}"

SEARCH_QUERIES = [
    {"keywords": "software developer fresher", "location": "India"},
    {"keywords": "intern developer", "location": "India"},
    {"keywords": "junior software engineer", "location": "India"},
]

HEADERS = {
    "User-Agent": "Whofy Job Aggregator (contact: rohanakode12@gmail.com)",
    "Content-Type": "application/json",
}


def fetch_jooble_jobs(query: dict) -> list[dict]:
    if not JOOBLE_API_KEY:
        print("  JOOBLE_API_KEY not set, skipping")
        return []

    url = JOOBLE_API.format(api_key=JOOBLE_API_KEY)
    payload = {
        "keywords": query["keywords"],
        "location": query["location"],
        "page": 1,
    }

    try:
        resp = requests.post(url, json=payload, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Error fetching Jooble ({query['keywords']}): {e}")
        return []

    data = resp.json()
    raw_jobs = data.get("jobs", [])

    normalized = []
    for job in raw_jobs:
        job_id = job.get("id", job.get("link", ""))
        title = job.get("title", "")
        location = job.get("location", "Not specified")
        # Jooble's API only ever gives a short snippet, not the full posting
        # — there's no separate "full text" to detect against here, unlike
        # the other sources.
        description = job.get("snippet", "")
        required_skills = extract_required_skills(title, description)
        normalized.append({
            "source": "jooble",
            "source_job_id": f"jbl_{job_id}",
            "title": title,
            "company": job.get("company", ""),
            "location": location,
            "description": bake_required_skills(description, required_skills),
            "apply_url": job.get("link", ""),
            "posted_at": job.get("updated", ""),
            "work_type": detect_work_type(title, location, description),
            "experience_level": detect_experience(title, description),
            "required_skills": required_skills,
        })

    return normalized


def main():
    if not JOOBLE_API_KEY:
        print("JOOBLE_API_KEY not set, skipping Jooble.")
        print("Sign up at https://jooble.org/api/about to get a free key.")
        return

    all_jobs = []

    for query in SEARCH_QUERIES:
        print(f"Fetching Jooble jobs ({query['keywords']})...")
        jobs = fetch_jooble_jobs(query)
        print(f"  -> {len(jobs)} jobs found")
        all_jobs.extend(jobs)

    print(f"\nTotal jobs fetched: {len(all_jobs)}")

    if all_jobs:
        result = save_jobs(all_jobs, source="jooble")
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
