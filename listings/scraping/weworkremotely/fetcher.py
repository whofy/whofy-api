import re
import warnings
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from listings.shared.enrich import bake_required_skills, detect_experience, detect_work_type, extract_required_skills
from listings.shared.normalize import full_text, strip_html
from listings.shared.storage import save_jobs
from listings.shared.tech_filter import filter_tech_jobs

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

RSS_URL = "https://weworkremotely.com/remote-jobs.rss"
MAX_AGE_DAYS = 30

HEADERS = {
    "User-Agent": "Whofy Job Aggregator (contact: whofyteam@gmail.com)"
}


def _parse_title(raw_title: str) -> tuple[str, str]:
    if ":" in raw_title:
        company, title = raw_title.split(":", 1)
        return company.strip(), title.strip()
    return "", raw_title.strip()


def _parse_date(item) -> str:
    pub_date = item.find("pubDate")
    if not pub_date:
        return ""
    try:
        dt = parsedate_to_datetime(pub_date.text)
        return dt.isoformat()
    except (ValueError, TypeError):
        return ""


def _is_within_age(posted_at: str) -> bool:
    if not posted_at:
        return False
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
        posted = datetime.fromisoformat(posted_at)
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        return posted >= cutoff
    except (ValueError, TypeError):
        return False


def _make_source_id(link: str) -> str:
    slug = link.rstrip("/").rsplit("/", 1)[-1] if link else ""
    return f"wwr_{slug}"


def fetch_wwr_jobs() -> list[dict]:
    try:
        resp = requests.get(RSS_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Error fetching We Work Remotely RSS: {e}")
        return []

    soup = BeautifulSoup(resp.text, "xml")
    items = soup.find_all("item")
    if not items:
        return []

    print(f"  -> {len(items)} items in RSS feed")

    normalized = []
    skipped_old = 0

    for item in items:
        raw_title = item.find("title")
        if not raw_title:
            continue

        company, title = _parse_title(raw_title.text)
        posted_at = _parse_date(item)

        if not _is_within_age(posted_at):
            skipped_old += 1
            continue

        link_tag = item.find("link")
        link = link_tag.text.strip() if link_tag else ""

        guid_tag = item.find("guid")
        guid = guid_tag.text.strip() if guid_tag else link

        region_tag = item.find("region")
        location = region_tag.text.strip() if region_tag else "Remote"

        desc_tag = item.find("description")
        raw_description = desc_tag.text if desc_tag else ""
        description = strip_html(raw_description)
        detection_text = full_text(raw_description)
        required_skills = extract_required_skills(title, detection_text)

        normalized.append({
            "source": "weworkremotely",
            "source_job_id": _make_source_id(guid or link),
            "title": title,
            "company": company,
            "location": location,
            "description": bake_required_skills(description, required_skills),
            "apply_url": link,
            "posted_at": posted_at,
            "work_type": "Remote",
            "experience_level": detect_experience(title, detection_text),
            "required_skills": required_skills,
        })

    if skipped_old:
        print(f"  -> {skipped_old} jobs skipped (older than {MAX_AGE_DAYS} days)")

    return normalized


def main():
    print("Fetching We Work Remotely jobs...")
    all_jobs = fetch_wwr_jobs()

    print(f"\nTotal jobs fetched: {len(all_jobs)}")

    all_jobs = filter_tech_jobs(all_jobs)
    print(f"After tech filter: {len(all_jobs)}")

    if all_jobs:
        result = save_jobs(all_jobs, source="weworkremotely")
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
