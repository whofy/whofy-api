import requests
from sources.shared.enrich import bake_required_skills, detect_experience, detect_work_type, extract_required_skills
from sources.shared.normalize import full_text, strip_html
from sources.shared.storage import save_jobs

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"

COMPANIES = [
    {"name": "Razorpay", "board_token": "razorpaysoftwareprivatelimited", "domain": "razorpay.com"},
    {"name": "Coinbase", "board_token": "coinbase", "domain": "coinbase.com"},
    {"name": "Airbnb", "board_token": "airbnb", "domain": "airbnb.com"},
    {"name": "DoorDash", "board_token": "doordashusa", "domain": "doordash.com"},
    {"name": "Stripe", "board_token": "stripe", "domain": "stripe.com"},
    {"name": "Twitch", "board_token": "twitch", "domain": "twitch.tv"},
    {"name": "Figma", "board_token": "figma", "domain": "figma.com"},
    {"name": "Discord", "board_token": "discord", "domain": "discord.com"},
    {"name": "Cloudflare", "board_token": "cloudflare", "domain": "cloudflare.com"},
    {"name": "Datadog", "board_token": "datadog", "domain": "datadoghq.com"},
    {"name": "Robinhood", "board_token": "robinhood", "domain": "robinhood.com"},
    {"name": "Pinterest", "board_token": "pinterest", "domain": "pinterest.com"},
    {"name": "Reddit", "board_token": "reddit", "domain": "reddit.com"},
    {"name": "Instacart", "board_token": "instacart", "domain": "instacart.com"},
    {"name": "Asana", "board_token": "asana", "domain": "asana.com"},
    {"name": "GitLab", "board_token": "gitlab", "domain": "gitlab.com"},
    {"name": "HashiCorp", "board_token": "hashicorp", "domain": "hashicorp.com"},
    {"name": "Affirm", "board_token": "affirm", "domain": "affirm.com"},
    {"name": "Notion", "board_token": "notion", "domain": "notion.so"},
    {"name": "Plaid", "board_token": "plaid", "domain": "plaid.com"},
    {"name": "Webflow", "board_token": "webflow", "domain": "webflow.com"},
    {"name": "Squarespace", "board_token": "squarespace", "domain": "squarespace.com"},
    {"name": "Brex", "board_token": "brex", "domain": "brex.com"},
    {"name": "Databricks", "board_token": "databricks", "domain": "databricks.com"},
    {"name": "Duolingo", "board_token": "duolingo", "domain": "duolingo.com"},
    {"name": "Postman", "board_token": "postman", "domain": "postman.com"},
    {"name": "Samsara", "board_token": "samsara", "domain": "samsara.com"},
    {"name": "Zscaler", "board_token": "zscaler", "domain": "zscaler.com"},
    {"name": "Gusto", "board_token": "gusto", "domain": "gusto.com"},
    {"name": "Vercel", "board_token": "vercel", "domain": "vercel.com"},
    {"name": "Anthropic", "board_token": "anthropic", "domain": "anthropic.com"},
]

HEADERS = {
    "User-Agent": "Whofy Job Aggregator (contact: rohanakode12@gmail.com)"
}


def fetch_greenhouse_jobs(company: dict) -> list[dict]:
    url = GREENHOUSE_API.format(board_token=company["board_token"])
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Error fetching {company['name']}: {e}")
        return []

    data = resp.json()
    raw_jobs = data.get("jobs", [])
    print(f"  -> {len(raw_jobs)} jobs found")

    normalized = []
    for job in raw_jobs:
        location = job.get("location", {}).get("name", "Not specified")
        title = job.get("title", "")
        raw_content = job.get("content", "")
        description = strip_html(raw_content)
        detection_text = full_text(raw_content)
        required_skills = extract_required_skills(title, detection_text)
        normalized.append({
            "source": "greenhouse",
            "source_job_id": f"gh_{job['id']}",
            "title": title,
            "company": company["name"],
            "company_domain": company.get("domain", ""),
            "location": location,
            "description": bake_required_skills(description, required_skills),
            "apply_url": job.get("absolute_url", ""),
            "posted_at": job.get("updated_at", ""),
            "work_type": detect_work_type(title, location, detection_text),
            "experience_level": detect_experience(title, detection_text),
            "required_skills": required_skills,
        })

    return normalized


def main():
    all_jobs = []

    for company in COMPANIES:
        print(f"Fetching jobs for {company['name']}...")
        jobs = fetch_greenhouse_jobs(company)
        all_jobs.extend(jobs)

    print(f"\nTotal jobs fetched: {len(all_jobs)}")

    if all_jobs:
        result = save_jobs(all_jobs, source="greenhouse")
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
