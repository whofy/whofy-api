from datetime import datetime
import requests
from listings.shared.storage import save_jobs

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
        title = job.get("position", "")
        location = job.get("location", "Remote")
        normalized.append({
            "source": "remoteok",
            "source_job_id": f"rok_{job.get('id', '')}",
            "title": title,
            "company": job.get("company", ""),
            "location": location,
            "raw_description": raw_description,
            "apply_url": job.get("url", ""),
            "posted_at": datetime.fromisoformat(job.get("date").replace("Z", "+00:00")) if job.get("date") else None,
            # RemoteOK is the only source that hands us a ready-made logo URL directly.
            "logo_url": job.get("company_logo") or None,
        })

    return normalized


from listings.shared.pipeline import process_jobs_batch

def main(mp_executor=None):
    print("Fetching RemoteOK jobs...")
    jobs = fetch_remoteok_jobs()

    print(f"\nTotal jobs fetched: {len(jobs)}")

    print("Running process_jobs_batch (enrichment + filtering)...")
    batch_result = process_jobs_batch(jobs, mp_executor=mp_executor)
    accepted_jobs = batch_result["accepted"]
    tech_filtered = batch_result["tech_filtered"]
    lang_filtered = batch_result["lang_filtered"]

    print(f"After MP enrichment/filter: {len(accepted_jobs)} accepted")
    print(f"Filtered (Tech): {tech_filtered}")
    print(f"Filtered (Lang): {lang_filtered}")

    if accepted_jobs:
        result = save_jobs(accepted_jobs, source="remoteok")
        result["tech_filtered"] = tech_filtered
        result["non_english_skipped"] = lang_filtered
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
