import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from listings.shared.pipeline import process_jobs_batch
from listings.shared.storage import save_jobs
from listings.shared.tech_filter import is_tech_job

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting"

MAX_AGE_DAYS = 30
PAGE_SIZE = 10
MAX_PAGES_PER_QUERY = 8
REQUEST_DELAY = 1.2
MAX_JOBS = 3000
TIME_FILTER = "r2592000"  # LinkedIn guest filter: past 30 days

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Whofy Job Aggregator; +https://whofy.io; contact: whofyteam@gmail.com)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

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
    "product manager",
    "cybersecurity analyst",
    "site reliability engineer",
    "python developer",
    "java developer",
    "react developer",
    "platform engineer",
    "security engineer",
]

LOCATIONS = [
    "United States",
    "India",
    "United Kingdom",
    "Canada",
    "Germany",
    "Australia",
    "Singapore",
    "Netherlands",
]


def _extract_job_id(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"-(\d{6,})(?:\?|$|/)", url)
    return match.group(1) if match else ""


def _clean_apply_url(url: str) -> str:
    if not url:
        return ""
    return url.split("?")[0].rstrip("/")


def _is_within_age(posted_at) -> bool:
    """F-13 fix — accept datetime | str | None, don't crash on wrong type."""
    if not posted_at:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    if isinstance(posted_at, datetime):
        posted = posted_at
    elif isinstance(posted_at, str):
        try:
            posted = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        except ValueError:
            return True
    else:
        return True
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    return posted >= cutoff


def _build_search_url(keywords: str, location: str, start: int) -> str:
    params = {
        "keywords": keywords,
        "location": location,
        "start": start,
        "f_TPR": TIME_FILTER,
    }
    return f"{SEARCH_URL}?{urlencode(params)}"


def _parse_search_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    listings = []

    for card in soup.find_all("li"):
        link_tag = card.find("a", class_="base-card__full-link")
        if not link_tag:
            continue

        apply_url = _clean_apply_url(link_tag.get("href", ""))
        job_id = _extract_job_id(apply_url)
        if not job_id:
            continue

        title_tag = card.find("h3", class_="base-search-card__title")
        company_tag = card.find("h4", class_="base-search-card__subtitle")
        location_tag = card.find("span", class_="job-search-card__location")
        time_tag = card.find("time")

        title = title_tag.get_text(strip=True) if title_tag else ""
        company = company_tag.get_text(strip=True) if company_tag else ""
        location = location_tag.get_text(strip=True) if location_tag else "Not specified"

        posted_at = ""
        if time_tag and time_tag.get("datetime"):
            posted_at = f"{time_tag['datetime']}T00:00:00+00:00"

        listings.append({
            "job_id": job_id,
            "title": title,
            "company": company,
            "location": location,
            "apply_url": apply_url or f"https://www.linkedin.com/jobs/view/{job_id}",
            "posted_at": datetime.fromisoformat(posted_at.replace("Z", "+00:00")) if posted_at else None,
        })

    return listings


def _fetch_search_page(keywords: str, location: str, start: int) -> list[dict]:
    url = _build_search_url(keywords, location, start)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Error fetching search page ({keywords!r}, {location!r}, start={start}): {e}")
        return []

    return _parse_search_page(resp.text)


def _fetch_job_detail(job_id: str) -> dict:
    url = f"{DETAIL_URL}/{job_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    desc_div = soup.find("div", class_="show-more-less-html__markup")
    raw_description = desc_div.decode_contents() if desc_div else ""

    title_tag = soup.find("h2", class_="top-card-layout__title")
    company_tag = soup.find("a", class_="topcard__org-name-link")
    location_tag = soup.find("span", class_="topcard__flavor--bullet")

    return {
        "title": title_tag.get_text(strip=True) if title_tag else "",
        "company": company_tag.get_text(strip=True) if company_tag else "",
        "location": location_tag.get_text(strip=True) if location_tag else "",
        "raw_description": raw_description,
    }


def _collect_listings() -> list[dict]:
    seen_ids: set[str] = set()
    collected: list[dict] = []
    total_combos = len(LOCATIONS) * len(SEARCH_QUERIES)
    combo_idx = 0

    for location in LOCATIONS:
        for query in SEARCH_QUERIES:
            combo_idx += 1
            if len(collected) >= MAX_JOBS:
                break

            print(f"  [{combo_idx}/{total_combos}] {query!r} in {location}...", flush=True)

            for page in range(MAX_PAGES_PER_QUERY):
                if len(collected) >= MAX_JOBS:
                    break

                start = page * PAGE_SIZE
                listings = _fetch_search_page(query, location, start)
                if not listings:
                    if page == 0:
                        print("    no results", flush=True)
                    break

                added = 0
                for listing in listings:
                    job_id = listing["job_id"]
                    if job_id in seen_ids:
                        continue
                    if not _is_within_age(listing.get("posted_at", "")):
                        continue
                    if not is_tech_job(listing.get("title", "")):
                        continue

                    seen_ids.add(job_id)
                    collected.append(listing)
                    added += 1

                    if len(collected) >= MAX_JOBS:
                        break

                print(
                    f"    page {page + 1}: +{added} new ({len(collected)} total)",
                    flush=True,
                )

                if added == 0 and page > 0:
                    break

                time.sleep(REQUEST_DELAY)

        if len(collected) >= MAX_JOBS:
            break

    return collected


def _enrich_listings(listings: list[dict]) -> list[dict]:
    """
    Post-F-13: returns RAW jobs (no inline enrichment).
    process_jobs_batch will run tech/lang filters + skill/work-type/experience detection.
    posted_at is passed through as-is (datetime, str, or None — process_jobs_batch handles it).
    """
    normalized = []

    for i, listing in enumerate(listings):
        job_id = listing["job_id"]
        detail = _fetch_job_detail(job_id)

        title = detail.get("title") or listing["title"]
        company = detail.get("company") or listing["company"]
        location = detail.get("location") or listing["location"]
        raw_description = detail.get("raw_description", "")

        normalized.append({
            "source": "linkedin",
            "source_job_id": f"li_{job_id}",
            "title": title,
            "company": company,
            "location": location,
            "raw_description": raw_description,
            "apply_url": listing["apply_url"],
            "posted_at": listing.get("posted_at"),  # datetime from _parse_search_page — no more crashes
        })

        if (i + 1) % 10 == 0 or i == 0:
            print(f"  -> enriched {i + 1}/{len(listings)} job details", flush=True)

        time.sleep(REQUEST_DELAY)

    return normalized


def fetch_linkedin_jobs() -> list[dict]:
    print("  Collecting LinkedIn job listings...")
    listings = _collect_listings()
    print(f"  -> {len(listings)} unique tech listings found")

    if not listings:
        return []

    print("  Fetching job descriptions...")
    return _enrich_listings(listings)


def main(mp_executor=None):
    print("Fetching LinkedIn jobs...")
    all_jobs = fetch_linkedin_jobs()
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
        result = save_jobs(accepted_jobs, source="linkedin")
        result["tech_filtered"] = tech_filtered
        result["non_english_skipped"] = lang_filtered
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
