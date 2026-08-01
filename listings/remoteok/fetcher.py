import requests
from listings.shared.enrich import bake_required_skills, detect_experience, detect_work_type, extract_required_skills
from listings.shared.normalize import full_text, strip_html
from listings.shared.storage import save_jobs
from listings.shared.tech_filter import filter_tech_jobs

REMOTEOK_API = "https://remoteok.com/api"

HEADERS = {
    "User-Agent": "Whofy Job Aggregator (contact: whofyteam@gmail.com)"
}


def fetch_remoteok_jobs() -> list[dict]:
    try:
        resp = requests.get(REMOTEOK_API, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Error fetching RemoteOK: {e}")
        return []

    raw_jobs = resp.json()
    if raw_jobs and isinstance(raw_jobs[0], dict) and "id" not in raw_jobs[0]:
        raw_jobs = raw_jobs[1:]

    print(f"  -> {len(raw_jobs)} jobs found")

    normalized = []
    for job in raw_jobs:
        raw_description = job.get("description", "")
        description = strip_html(raw_description)
        detection_text = full_text(raw_description)
        title = job.get("position", "")
        location = job.get("location", "Remote")
        required_skills = extract_required_skills(title, detection_text)
        normalized.append({
            "source": "remoteok",
            "source_job_id": f"rok_{job.get('id', '')}",
            "title": title,
            "company": job.get("company", ""),
            "location": location,
            "description": bake_required_skills(description, required_skills),
            "apply_url": job.get("url", ""),
            "posted_at": job.get("date", ""),
            "work_type": detect_work_type(title, location, detection_text),
            "experience_level": detect_experience(title, detection_text),
            "required_skills": required_skills,
        })

    return normalized


def main():
    print("Fetching RemoteOK jobs...")
    jobs = fetch_remoteok_jobs()

    print(f"\nTotal jobs fetched: {len(jobs)}")

    jobs = filter_tech_jobs(jobs)
    print(f"After tech filter: {len(jobs)}")

    if jobs:
        result = save_jobs(jobs, source="remoteok")
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
