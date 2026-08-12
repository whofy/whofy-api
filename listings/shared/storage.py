import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
from pymongo import UpdateOne
try:
    from langdetect import detect, LangDetectException, DetectorFactory
    DetectorFactory.seed = 0
except ImportError:
    pass

from db.mongo import get_client

DB_NAME = "whofy"
JOBS_COLLECTION = "jobs"
DEFAULT_SOURCE_CAP = 20000
EXPIRY_DAYS = 28
MAX_AGE_DAYS = 28


def _fingerprint(source: str, source_job_id: str) -> str:
    """Source-scoped upsert key — same source's same job → same fingerprint."""
    raw = f"{source}||{source_job_id}".lower()
    return re.sub(r"[^a-z0-9|]", "", raw)


# Company legal suffixes — stripped when computing canonical_fingerprint so
# "Anthropic PBC" and "Anthropic" collapse to the same key.
_LEGAL_SUFFIXES_RE = re.compile(
    r"\b(inc|llc|corp|corporation|ltd|limited|pbc|gmbh|co)\b",
    re.IGNORECASE,
)


def _canonical_fingerprint(company: str, title: str, location: str) -> str:
    """
    Cross-source dedup key. Same real-world job on multiple sources → same fingerprint.
    Consumed by pipeline/dedupe_jobs.py to remove duplicate rows.
    """
    def norm(s: str) -> str:
        s = (s or "").lower()
        s = _LEGAL_SUFFIXES_RE.sub("", s)
        s = re.sub(r"[^a-z0-9]", "", s)
        return s
    return f"{norm(company)}||{norm(title)}||{norm(location)}"


# ── Location canonicalization data loaded from data/locations.yml ──
# To add cities/countries/states/remote-keywords, edit data/locations.yml.
_LOCATIONS_YML = Path(__file__).parent.parent.parent / 'data' / 'locations.yml'
_loc_data = yaml.safe_load(_LOCATIONS_YML.read_text(encoding='utf-8'))
COUNTRY_CODE_MAP = _loc_data['country_codes']
KNOWN_CITIES = _loc_data['known_cities']
_STATES = set(_loc_data['states'])
REMOTE_KEYWORDS = set(_loc_data['remote_keywords'])

STRIP_PATTERNS = [
    re.compile(r"\s*-\s*[^,]+(?=,|$)"),
    re.compile(r"\s*\([^)]*\)\s*"),
]


def _normalize_location(raw: str) -> str:
    if not raw or not raw.strip():
        return ""

    loc = raw.strip()

    if loc.lower() in REMOTE_KEYWORDS:
        return "Remote"

    if ";" in loc:
        parts = [_normalize_location(p.strip()) for p in loc.split(";")]
        seen = set()
        unique = []
        for p in parts:
            if p and p not in seen and p != "Remote":
                seen.add(p)
                unique.append(p)
        return "; ".join(unique) if unique else "Remote"

    for pattern in STRIP_PATTERNS:
        loc = pattern.sub("", loc)

    parts = [p.strip() for p in loc.split(",") if p.strip()]
    if not parts:
        return raw.strip()

    city = None
    country = None
    conflict = False

    for part in parts:
        lower = part.lower().strip()
        if lower in COUNTRY_CODE_MAP:
            matched_country = COUNTRY_CODE_MAP[lower]
            if country and country != matched_country:
                conflict = True
            country = matched_country
        elif lower in KNOWN_CITIES:
            city_name = part.strip()
            # If city is already set and it's a different city, conflict
            if city and city.lower() != city_name.lower():
                conflict = True
            city = city_name
            
            matched_country = KNOWN_CITIES[lower]
            if country and country != matched_country:
                conflict = True
            if not country:
                country = matched_country

    if conflict:
        return raw.strip()

    if not city:
        for part in parts:
            lower = part.lower().strip()
            if lower not in COUNTRY_CODE_MAP and lower not in KNOWN_CITIES:
                if lower not in _STATES:
                    city = part.strip()
                    break

    if city and country:
        return f"{city}, {country}"
    if city:
        return city
    if country:
        return country
    return parts[0]


def _is_non_english(job: dict) -> bool:
    if job.get("lang_checked"):
        return False
        
    title = job.get("title") or ""
    desc = job.get("description") or ""
    desc = desc[:500]
    
    text = f"{title} {desc}".strip()
    if not text:
        return False
        
    try:
        lang = detect(text)
        return lang != "en"
    except Exception:
        return False


def _is_too_old(posted_at) -> bool:
    if not posted_at:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    if isinstance(posted_at, datetime):
        posted = posted_at
    elif isinstance(posted_at, str):
        try:
            posted = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        except ValueError:
            return False
    else:
        return False
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    return posted < cutoff


def save_jobs(jobs: list[dict], source: str, cap: int = DEFAULT_SOURCE_CAP) -> dict:
    if not jobs:
        return {"source": source, "upserted": 0, "modified": 0, "capped": False}

    before = len(jobs)
    jobs = [j for j in jobs if not _is_too_old(j.get("posted_at", ""))]
    too_old = before - len(jobs)

    before_lang = len(jobs)
    jobs = [j for j in jobs if not _is_non_english(j)]
    non_english = before_lang - len(jobs)

    for job in jobs:
        raw_loc = job.get("location", "")
        if raw_loc:
            job["location"] = _normalize_location(raw_loc)

    for job in jobs:
        job["fingerprint"] = _fingerprint(source, job.get("source_job_id", ""))
        # Cross-source dedup key — populated on every save. Same real-world job
        # from multiple sources gets the same value. Cleanup handled by
        # pipeline/dedupe_jobs.py running after ingestion.
        job["canonical_fingerprint"] = _canonical_fingerprint(
            job.get("company", ""),
            job.get("title", ""),
            job.get("location", ""),
        )

    capped = False
    if len(jobs) > cap:
        jobs = sorted(
            jobs, key=lambda j: j.get("posted_at") or "", reverse=True
        )[:cap]
        capped = True

    client = get_client()
    db = client[DB_NAME]
    collection = db[JOBS_COLLECTION]

    fingerprints = [j["fingerprint"] for j in jobs]
    existing = set()
    if fingerprints:
        cursor = collection.find(
            {"fingerprint": {"$in": fingerprints}, "source": {"$ne": source}},
            {"fingerprint": 1},
        )
        existing = {doc["fingerprint"] for doc in cursor}

    now = datetime.now(timezone.utc).isoformat()
    skipped = 0

    from models.job import Job
    operations = []
    schema_rejected = 0
    for job in jobs:
        if job["fingerprint"] in existing:
            skipped += 1
            continue
        job["last_seen_at"] = now
        job["lang_checked"] = True

        if "added_at" not in job:
            job["added_at"] = now

        try:
            validated_job = Job.model_validate(job).model_dump(by_alias=True)
        except Exception:
            schema_rejected += 1
            continue

        added_at_val = validated_job.pop("added_at", now)
        validated_job.pop("_id", None)

        operations.append(
            UpdateOne(
                {"source": source, "source_job_id": validated_job["source_job_id"]},
                {"$set": validated_job, "$setOnInsert": {"added_at": added_at_val}},
                upsert=True,
            )
        )

    result_info = {
        "source": source,
        "upserted": 0,
        "modified": 0,
        "capped": capped,
        "total_processed": len(jobs),
        "cross_source_skipped": skipped,
        "too_old_skipped": too_old,
        "non_english_skipped": non_english,
        "schema_rejected": schema_rejected,
    }

    if operations:
        result = collection.bulk_write(operations, ordered=False)
        result_info["upserted"] = result.upserted_count
        result_info["modified"] = result.modified_count

    if schema_rejected > 0:
        print(f"[{source}] SCHEMA REJECTED: {schema_rejected} jobs")

    return result_info


from concurrent.futures import ProcessPoolExecutor

def _process_batch(docs):
    to_delete = []
    to_mark = []
    for doc in docs:
        if _is_non_english(doc):
            to_delete.append(doc["_id"])
        else:
            to_mark.append(doc["_id"])
    return {"to_delete": to_delete, "to_mark": to_mark}

def cleanup_non_english_jobs() -> int:
    client = get_client()
    db = client[DB_NAME]
    collection = db[JOBS_COLLECTION]

    removed = 0
    batch_size = 2000
    batch = []

    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = []
        for doc in collection.find({"lang_checked": {"$ne": True}}, {"title": 1, "description": 1}):
            batch.append(doc)
            if len(batch) >= batch_size:
                futures.append(executor.submit(_process_batch, batch))
                batch = []
        if batch:
            futures.append(executor.submit(_process_batch, batch))
            
        all_to_delete = []
        all_to_mark = []
        for future in futures:
            res = future.result()
            all_to_delete.extend(res["to_delete"])
            all_to_mark.extend(res["to_mark"])

    if all_to_delete:
        chunk_size = 1000
        for i in range(0, len(all_to_delete), chunk_size):
            chunk = all_to_delete[i:i + chunk_size]
            collection.delete_many({"_id": {"$in": chunk}})
        removed = len(all_to_delete)
        
    if all_to_mark:
        chunk_size = 1000
        for i in range(0, len(all_to_mark), chunk_size):
            chunk = all_to_mark[i:i + chunk_size]
            collection.update_many({"_id": {"$in": chunk}}, {"$set": {"lang_checked": True}})

    return removed


def cleanup_expired_jobs(expiry_days: int = EXPIRY_DAYS) -> int:
    client = get_client()
    db = client[DB_NAME]
    collection = db[JOBS_COLLECTION]

    cutoff = datetime.now(timezone.utc) - timedelta(days=expiry_days)
    result = collection.delete_many({"last_seen_at": {"$lt": cutoff}})
    return result.deleted_count


def ensure_indexes():
    client = get_client()
    db = client[DB_NAME]
    collection = db[JOBS_COLLECTION]

    collection.create_index([("source", 1), ("source_job_id", 1)], unique=True)
    collection.create_index([("posted_at", -1), ("_id", 1)])
    collection.create_index([("last_seen_at", -1)])
    collection.create_index([("added_at", -1)])
    collection.create_index([("title", "text"), ("description", "text")])
    collection.create_index([("work_type", 1)])
    collection.create_index([("experience_level", 1)])
    collection.create_index("canonical_fingerprint")  # for cross-source dedup grouping

    saved_jobs_col = db["saved_jobs"]
    saved_jobs_col.create_index([("user_id", 1), ("job_id", 1)], unique=True)
    saved_jobs_col.create_index([("user_id", 1), ("saved_at", -1)])

    print("Indexes ensured.")


def get_collection_stats() -> dict:
    client = get_client()
    db = client[DB_NAME]
    collection = db[JOBS_COLLECTION]

    total = collection.count_documents({})
    pipeline = [{"$group": {"_id": "$source", "count": {"$sum": 1}}}]
    per_source = {doc["_id"]: doc["count"] for doc in collection.aggregate(pipeline)}
    return {"total_jobs": total, "per_source": per_source}


if __name__ == "__main__":
    stats = get_collection_stats()
    print(f"Total jobs in DB: {stats['total_jobs']}")
    print("Per source:")
    for source, count in stats["per_source"].items():
        cap_note = " (at/near cap)" if count >= DEFAULT_SOURCE_CAP * 0.9 else ""
        print(f"  {source}: {count}{cap_note}")
