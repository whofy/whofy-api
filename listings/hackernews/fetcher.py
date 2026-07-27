import re
import time
import requests
from datetime import datetime, timezone

from listings.shared.enrich import (
    bake_required_skills, detect_experience, detect_work_type, extract_required_skills,
)
from listings.shared.normalize import strip_html
from listings.shared.storage import save_jobs
from listings.shared.tech_filter import filter_tech_jobs

ALGOLIA_API = "https://hn.algolia.com/api/v1/search_by_date"
FIREBASE_ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
BATCH_SIZE = 20
REQUEST_DELAY = 0.3

HEADERS = {
    "User-Agent": "Whofy Job Aggregator (contact: whofyteam@gmail.com)"
}


def _find_latest_thread() -> dict | None:
    params = {
        "query": '"Ask HN: Who is hiring"',
        "tags": "ask_hn",
        "hitsPerPage": 5,
        "numericFilters": "created_at_i>1704067200",
    }
    try:
        resp = requests.get(ALGOLIA_API, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Error searching Algolia: {e}")
        return None

    hits = resp.json().get("hits", [])
    who_hiring = [
        h for h in hits
        if re.match(r"Ask HN: Who is hiring\??\s*\(", h.get("title", ""))
    ]
    if not who_hiring:
        return None

    who_hiring.sort(key=lambda h: h.get("created_at_i", 0), reverse=True)
    latest = who_hiring[0]
    return {
        "id": int(latest["objectID"]),
        "title": latest.get("title", ""),
        "created_at": latest.get("created_at", ""),
    }


def _fetch_thread_kids(thread_id: int) -> list[int]:
    url = FIREBASE_ITEM.format(id=thread_id)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json().get("kids", [])
    except requests.RequestException as e:
        print(f"  Error fetching thread: {e}")
        return []


def _fetch_comment(comment_id: int) -> dict | None:
    url = FIREBASE_ITEM.format(id=comment_id)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data and data.get("type") == "comment" and not data.get("deleted") and not data.get("dead"):
            return data
    except requests.RequestException:
        pass
    return None


def _parse_header(text: str) -> dict:
    first_line = text.split("\n")[0].strip()
    first_line = re.sub(r"<[^>]+>", "", first_line).strip()

    parts = re.split(r"\s*\|\s*", first_line)

    company = parts[0].strip() if len(parts) >= 1 else ""
    title = parts[1].strip() if len(parts) >= 2 else ""
    location = ""
    work_type = ""

    for part in parts[2:]:
        p = part.strip().lower()
        if any(kw in p for kw in ["remote", "hybrid", "onsite", "on-site", "in-office"]):
            if "remote" in p:
                work_type = "Remote"
            elif "hybrid" in p:
                work_type = "Hybrid"
            else:
                work_type = "On-site"
            if not location:
                location = part.strip()
        elif not location and len(part.strip()) > 1:
            location = part.strip()

    if not location:
        location = "Not specified"

    return {
        "company": company,
        "title": title,
        "location": location,
        "work_type": work_type,
    }


def fetch_hn_jobs(thread_id: int, thread_date: str) -> list[dict]:
    kids = _fetch_thread_kids(thread_id)
    if not kids:
        return []

    print(f"  -> {len(kids)} top-level comments to process")

    all_jobs = []

    for i in range(0, len(kids), BATCH_SIZE):
        batch = kids[i:i + BATCH_SIZE]
        for comment_id in batch:
            comment = _fetch_comment(comment_id)
            if not comment:
                continue

            text = comment.get("text", "")
            if not text or len(text) < 50:
                continue

            header = _parse_header(text)
            if not header["company"] or not header["title"]:
                continue

            clean_text = strip_html(text)
            required_skills = extract_required_skills(header["title"], clean_text)

            wt = header["work_type"]
            if not wt:
                wt = detect_work_type(header["title"], header["location"], clean_text)

            all_jobs.append({
                "source": "hackernews",
                "source_job_id": f"hn_{comment_id}",
                "title": header["title"],
                "company": header["company"],
                "company_domain": "",
                "location": header["location"],
                "description": bake_required_skills(clean_text, required_skills),
                "apply_url": f"https://news.ycombinator.com/item?id={comment_id}",
                "posted_at": thread_date,
                "work_type": wt,
                "experience_level": detect_experience(header["title"], clean_text),
                "required_skills": required_skills,
            })

            time.sleep(REQUEST_DELAY)

        if (i + BATCH_SIZE) % 100 == 0:
            print(f"  ... processed {min(i + BATCH_SIZE, len(kids))}/{len(kids)} comments")

    return all_jobs


def main():
    print("Finding latest HN 'Who is hiring?' thread...")
    thread = _find_latest_thread()
    if not thread:
        print("No thread found.")
        return

    print(f"  Found: {thread['title']} (ID: {thread['id']})")

    print("Fetching jobs...")
    all_jobs = fetch_hn_jobs(thread["id"], thread["created_at"])
    print(f"Total jobs parsed: {len(all_jobs)}")

    all_jobs = filter_tech_jobs(all_jobs)
    print(f"After tech filter: {len(all_jobs)}")

    if all_jobs:
        result = save_jobs(all_jobs, source="hackernews")
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
