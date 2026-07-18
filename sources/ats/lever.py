import requests
from sources.shared.enrich import bake_required_skills, detect_experience, detect_work_type, extract_required_skills
from sources.shared.normalize import extract_bullets, first_paragraph
from sources.shared.storage import save_jobs

LEVER_API = "https://api.lever.co/v0/postings/{company}?mode=json"

COMPANIES = [
    {"name": "Spotify", "slug": "spotify", "domain": "spotify.com"},
    {"name": "Palantir", "slug": "palantir", "domain": "palantir.com"},
    {"name": "Gopuff", "slug": "gopuff", "domain": "gopuff.com"},
]

HEADERS = {
    "User-Agent": "Whofy Job Aggregator (contact: rohanakode12@gmail.com)"
}

# Lever exposes an explicit workplaceType on many postings — a structured
# signal beats regex-guessing from text when it's present.
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
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Error fetching {company['name']}: {e}")
        return []

    raw_jobs = resp.json()
    print(f"  -> {len(raw_jobs)} jobs found")

    normalized = []
    for job in raw_jobs:
        categories = job.get("categories", {})
        location = categories.get("location", "Not specified")

        # Lever splits postings into a plain-text intro (descriptionPlain)
        # and separate bulleted sections (lists[] — e.g. "Responsibilities",
        # "Requirements", each with its own HTML content). The display
        # description only uses the intro + first list (keeps job cards
        # short), but detection needs to see every list — the tech-stack
        # requirements often live in a later section, not the first one.
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

    if all_jobs:
        result = save_jobs(all_jobs, source="lever")
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
