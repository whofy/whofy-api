import requests
from listings.shared.enrich import bake_required_skills, detect_experience, detect_work_type, extract_required_skills
from listings.shared.normalize import extract_bullets, first_paragraph
from listings.shared.storage import save_jobs
from listings.shared.tech_filter import filter_tech_jobs

LEVER_API = "https://api.lever.co/v0/postings/{company}?mode=json"

COMPANIES = [
    {"name": "Gopuff", "slug": "gopuff", "domain": "gopuff.com"},
    {"name": "Palantir", "slug": "palantir", "domain": "palantir.com"},
    {"name": "Spotify", "slug": "spotify", "domain": "spotify.com"},
    {"name": "LogRocket", "slug": "logrocket", "domain": "logrocket.com"},
    {"name": "Tinybird", "slug": "tinybird", "domain": "tinybird.co"},
    {"name": "Outreach", "slug": "outreach", "domain": "outreach.io"},
    {"name": "Cloudinary", "slug": "cloudinary", "domain": "cloudinary.com"},
    {"name": "Toptal", "slug": "toptal", "domain": "toptal.com"},
    {"name": "JumpCloud", "slug": "jumpcloud", "domain": "jumpcloud.com"},
    {"name": "StackBlitz", "slug": "stackblitz", "domain": "stackblitz.com"},
]

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
        required_skills = extract_required_skills(title, detection_text)

        workplace_type = WORKPLACE_TYPE_MAP.get((categories.get("workplaceType") or "").lower())
        work_type = workplace_type or detect_work_type(title, location, detection_text)

        normalized.append({
            "source": "lever",
            "source_job_id": f"lv_{job['id']}",
            "title": title,
            "company": company["name"],
            "company_domain": company.get("domain", ""),
            "location": location,
            "description": bake_required_skills(description, required_skills),
            "apply_url": job.get("hostedUrl", ""),
            "posted_at": "",
            "work_type": work_type,
            "experience_level": detect_experience(title, detection_text),
            "required_skills": required_skills,
        })

    return normalized


def main():
    all_jobs = []

    for company in COMPANIES:
        print(f"Fetching jobs for {company['name']}...")
        jobs = fetch_lever_jobs(company)
        all_jobs.extend(jobs)

    print(f"\nTotal jobs fetched: {len(all_jobs)}")

    all_jobs = filter_tech_jobs(all_jobs)
    print(f"After tech filter: {len(all_jobs)}")

    if all_jobs:
        result = save_jobs(all_jobs, source="lever")
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
