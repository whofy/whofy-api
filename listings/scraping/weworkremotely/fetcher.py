import re
import warnings
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from listings.shared.pipeline import process_jobs_batch
from listings.shared.storage import save_jobs

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

        normalized.append({
            "source": "weworkremotely",
            "source_job_id": _make_source_id(guid or link),
            "title": title,
            "company": company,
            "location": location,
            "raw_description": raw_description,
            "apply_url": link,
            "posted_at": posted_at,
            "work_type": "Remote",  # WWR is a remote-only board — always Remote
        })

    if skipped_old:
        print(f"  -> {skipped_old} jobs skipped (older than {MAX_AGE_DAYS} days)")

    return normalized


def main(mp_executor=None):
    print("Fetching We Work Remotely jobs...")
    all_jobs = fetch_wwr_jobs()
    print(f"\nTotal jobs fetched: {len(all_jobs)}")

    print("Running process_jobs_batch (enrichment + filtering)...")
    batch_result = process_jobs_batch(all_jobs, mp_executor=mp_executor)
    accepted_jobs = batch_result["accepted"]
    tech_filtered = batch_result["tech_filtered"]
    lang_filtered = batch_result["lang_filtered"]
    print(f"After MP enrichment/filter: {len(accepted_jobs)} accepted")
    print(f"Filtered (Tech): {tech_filtered}")
    print(f"Filtered (Lang): {lang_filtered}")

    if accepted_jobs:
        result = save_jobs(accepted_jobs, source="weworkremotely")
        result["tech_filtered"] = tech_filtered
        result["non_english_skipped"] = lang_filtered
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
