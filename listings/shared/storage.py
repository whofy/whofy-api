import re
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient, UpdateOne
import certifi
try:
    from langdetect import detect, LangDetectException, DetectorFactory
    DetectorFactory.seed = 0
except ImportError:
    pass

from config.settings import settings

MONGODB_URI = settings.mongodb_uri
DB_NAME = "whofy"
JOBS_COLLECTION = "jobs"
LOGOS_COLLECTION = "company_logos"
DEFAULT_SOURCE_CAP = 20000
EXPIRY_DAYS = 28
MAX_AGE_DAYS = 28


_client_instance = None
def get_client() -> MongoClient:
    global _client_instance
    if _client_instance is not None:
        return _client_instance
    if not MONGODB_URI:
        raise RuntimeError("MONGODB_URI environment variable is not set")
    _client_instance = MongoClient(MONGODB_URI, tlsCAFile=certifi.where())
    return _client_instance


def _fingerprint(source: str, source_job_id: str) -> str:
    raw = f"{source}||{source_job_id}".lower()
    return re.sub(r"[^a-z0-9|]", "", raw)


def is_link_alive(url: str) -> bool:
    try:
        resp = requests.head(url, timeout=5, allow_redirects=True,
                             headers={"User-Agent": "Whofy Link Checker"})
        return resp.status_code < 400
    except requests.RequestException:
        return False


def filter_dead_links(jobs: list[dict]) -> tuple[list[dict], int]:
    if not jobs:
        return jobs, 0

    urls = [job.get("apply_url", "") for job in jobs]

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(is_link_alive, urls))

    alive = [job for job, ok in zip(jobs, results) if ok]
    dead_count = len(jobs) - len(alive)
    return alive, dead_count


COUNTRY_CODE_MAP = {
    "in": "India", "ind": "India", "india": "India",
    "us": "United States", "usa": "United States", "united states": "United States",
    "uk": "United Kingdom", "gb": "United Kingdom", "united kingdom": "United Kingdom",
    "ca": "Canada", "canada": "Canada",
    "au": "Australia", "australia": "Australia",
    "de": "Germany", "germany": "Germany",
    "fr": "France", "france": "France",
    "nl": "Netherlands", "netherlands": "Netherlands",
    "sg": "Singapore", "singapore": "Singapore",
    "br": "Brazil", "brazil": "Brazil",
    "nz": "New Zealand", "new zealand": "New Zealand",
    "pl": "Poland", "poland": "Poland",
    "ae": "UAE", "uae": "UAE", "united arab emirates": "UAE",
    "jp": "Japan", "japan": "Japan",
    "kr": "South Korea", "south korea": "South Korea",
    "cn": "China", "china": "China",
    "ie": "Ireland", "ireland": "Ireland",
    "il": "Israel", "israel": "Israel",
    "se": "Sweden", "sweden": "Sweden",
    "ch": "Switzerland", "switzerland": "Switzerland",
    "es": "Spain", "spain": "Spain",
    "it": "Italy", "italy": "Italy",
    "mx": "Mexico", "mexico": "Mexico",
}

KNOWN_CITIES = {
    "mumbai": "India", "delhi": "India", "bengaluru": "India", "bangalore": "India",
    "hyderabad": "India", "chennai": "India", "kolkata": "India", "pune": "India",
    "ahmedabad": "India", "jaipur": "India", "lucknow": "India", "kanpur": "India",
    "nagpur": "India", "indore": "India", "thane": "India", "bhopal": "India",
    "visakhapatnam": "India", "noida": "India", "gurugram": "India", "gurgaon": "India",
    "chandigarh": "India", "coimbatore": "India", "kochi": "India", "cochin": "India",
    "thiruvananthapuram": "India", "trivandrum": "India", "mangalore": "India",
    "mysore": "India", "mysuru": "India", "vadodara": "India", "surat": "India",
    "rajkot": "India", "mohali": "India", "goa": "India", "dehradun": "India",
    "patna": "India", "ranchi": "India", "bhubaneswar": "India", "guwahati": "India",
    "new york": "United States", "san francisco": "United States", "seattle": "United States",
    "austin": "United States", "chicago": "United States", "boston": "United States",
    "los angeles": "United States", "denver": "United States", "atlanta": "United States",
    "london": "United Kingdom", "berlin": "Germany", "paris": "France",
    "toronto": "Canada", "vancouver": "Canada", "sydney": "Australia",
    "melbourne": "Australia", "amsterdam": "Netherlands", "dublin": "Ireland",
    "singapore": "Singapore", "tokyo": "Japan",
}

REMOTE_KEYWORDS = {"remote", "work from home", "wfh", "anywhere", "distributed"}

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

    for part in parts:
        lower = part.lower().strip()
        if lower in COUNTRY_CODE_MAP:
            country = COUNTRY_CODE_MAP[lower]
        elif lower in KNOWN_CITIES:
            city = part.strip()
            if not country:
                country = KNOWN_CITIES[lower]

    if not city:
        for part in parts:
            lower = part.lower().strip()
            if lower not in COUNTRY_CODE_MAP and lower not in KNOWN_CITIES:
                if not any(lower == s for s in [
                    "telangana", "karnataka", "maharashtra", "tamil nadu",
                    "andhra pradesh", "west bengal", "rajasthan", "gujarat",
                    "uttar pradesh", "madhya pradesh", "kerala", "haryana",
                    "bihar", "odisha", "jharkhand", "assam", "punjab",
                    "uttarakhand", "himachal pradesh", "chhattisgarh",
                    "california", "texas", "new york", "washington",
                    "massachusetts", "illinois", "colorado", "georgia",
                    "florida", "virginia", "oregon", "pennsylvania",
                    "north carolina", "ohio", "michigan", "minnesota",
                    "maryland", "connecticut", "new jersey", "arizona",
                    "england", "scotland", "wales",
                    "ontario", "british columbia", "quebec",
                    "bavaria", "hesse", "north rhine-westphalia",
                    "new south wales", "victoria", "queensland",
                ]):
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
    title = job.get("title", "")
    desc = job.get("description", "")[:500]
    
    text = f"{title} {desc}".strip()
    if not text:
        return False
        
    try:
        lang = detect(text)
        return lang != "en"
    except Exception:
        return False


def _is_too_old(posted_at: str) -> bool:
    if not posted_at:
        return False
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
        posted = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        return posted < cutoff
    except (ValueError, TypeError):
        return False


def save_jobs(jobs: list[dict], source: str, cap: int = DEFAULT_SOURCE_CAP) -> dict:
    import time
    t_start = time.time()
    if not jobs:
        return {"source": source, "upserted": 0, "modified": 0, "capped": False}

    before = len(jobs)
    jobs = [j for j in jobs if not _is_too_old(j.get("posted_at", ""))]
    too_old = before - len(jobs)
    t_old = time.time()
    t_lang = time.time()

    for job in jobs:
        raw_loc = job.get("location", "")
        if raw_loc:
            job["location"] = _normalize_location(raw_loc)
    t_loc = time.time()

    from listings.shared.logos import attach_logos
    logos_attached = attach_logos(jobs)
    t_logos = time.time()

    for job in jobs:
        job["fingerprint"] = _fingerprint(source, job.get("source_job_id", ""))

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
    t_in = time.time()

    now = datetime.now(timezone.utc).isoformat()
    skipped = 0

    operations = []
    for job in jobs:
        if job["fingerprint"] in existing:
            skipped += 1
            continue
        job["last_seen_at"] = now
        job["lang_checked"] = True
        operations.append(
            UpdateOne(
                {"source": source, "source_job_id": job["source_job_id"]},
                {"$set": job, "$setOnInsert": {"added_at": now}},
                upsert=True,
            )
        )
    t_ops = time.time()

    result_info = {
        "source": source,
        "upserted": 0,
        "modified": 0,
        "capped": capped,
        "total_processed": len(jobs),
        "cross_source_skipped": skipped,
        "too_old_skipped": too_old,
        "logos_attached": logos_attached,
    }

    if operations:
        result = collection.bulk_write(operations, ordered=False)
        result_info["upserted"] = result.upserted_count
        result_info["modified"] = result.modified_count
    t_bulk = time.time()

    if source == "greenhouse":
        print(f"\n[Greenhouse save_jobs Profiling]")
        print(f" - Too old filter: {t_old - t_start:.2f}s")
        print(f" - Langdetect: {t_lang - t_old:.2f}s")
        print(f" - Location norm: {t_loc - t_lang:.2f}s")
        print(f" - attach_logos: {t_logos - t_loc:.2f}s")
        print(f" - $in query: {t_in - t_logos:.2f}s")
        print(f" - build ops: {t_ops - t_in:.2f}s")
        print(f" - bulk_write: {t_bulk - t_ops:.2f}s")
        print(f" - Total save_jobs: {t_bulk - t_start:.2f}s\n")

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


def normalize_existing_locations() -> int:
    client = get_client()
    db = client[DB_NAME]
    collection = db[JOBS_COLLECTION]

    updated = 0
    for doc in collection.find({}, {"location": 1}):
        raw = doc.get("location", "")
        if not raw:
            continue
        normalized = _normalize_location(raw)
        if normalized != raw:
            collection.update_one({"_id": doc["_id"]}, {"$set": {"location": normalized}})
            updated += 1

    return updated


def cleanup_expired_jobs(expiry_days: int = EXPIRY_DAYS) -> int:
    client = get_client()
    db = client[DB_NAME]
    collection = db[JOBS_COLLECTION]

    cutoff = (datetime.now(timezone.utc) - timedelta(days=expiry_days)).isoformat()
    result = collection.delete_many({
        "$or": [
            {"added_at": {"$lt": cutoff}},
            {"added_at": {"$exists": False}, "last_seen_at": {"$lt": cutoff}},
        ]
    })
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

    logos_col = db[LOGOS_COLLECTION]
    logos_col.create_index("company_key", unique=True)

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
