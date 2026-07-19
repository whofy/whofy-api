import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient, UpdateOne

from config.settings import settings

MONGODB_URI = settings.mongodb_uri
DB_NAME = "whofy"
JOBS_COLLECTION = "jobs"
DEFAULT_SOURCE_CAP = 7000
EXPIRY_DAYS = 5


def get_client() -> MongoClient:
    if not MONGODB_URI:
        raise RuntimeError("MONGODB_URI environment variable is not set")
    return MongoClient(MONGODB_URI)


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


def save_jobs(jobs: list[dict], source: str, cap: int = DEFAULT_SOURCE_CAP) -> dict:
    if not jobs:
        return {"source": source, "upserted": 0, "modified": 0, "capped": False}

    capped = False
    if len(jobs) > cap:
        jobs = sorted(
            jobs, key=lambda j: j.get("posted_at") or "", reverse=True
        )[:cap]
        capped = True

    client = get_client()
    db = client[DB_NAME]
    collection = db[JOBS_COLLECTION]

    now = datetime.now(timezone.utc).isoformat()

    operations = []
    for job in jobs:
        job["last_seen_at"] = now
        operations.append(
            UpdateOne(
                {"source": source, "source_job_id": job["source_job_id"]},
                {"$set": job},
                upsert=True,
            )
        )

    result = collection.bulk_write(operations, ordered=False)
    client.close()

    return {
        "source": source,
        "upserted": result.upserted_count,
        "modified": result.modified_count,
        "capped": capped,
        "total_processed": len(jobs),
    }


def cleanup_expired_jobs(expiry_days: int = EXPIRY_DAYS) -> int:
    client = get_client()
    db = client[DB_NAME]
    collection = db[JOBS_COLLECTION]

    cutoff = (datetime.now(timezone.utc) - timedelta(days=expiry_days)).isoformat()
    result = collection.delete_many({"last_seen_at": {"$lt": cutoff}})
    client.close()
    return result.deleted_count


def get_collection_stats() -> dict:
    client = get_client()
    db = client[DB_NAME]
    collection = db[JOBS_COLLECTION]

    total = collection.count_documents({})
    pipeline = [{"$group": {"_id": "$source", "count": {"$sum": 1}}}]
    per_source = {doc["_id"]: doc["count"] for doc in collection.aggregate(pipeline)}
    client.close()
    return {"total_jobs": total, "per_source": per_source}


if __name__ == "__main__":
    stats = get_collection_stats()
    print(f"Total jobs in DB: {stats['total_jobs']}")
    print("Per source:")
    for source, count in stats["per_source"].items():
        cap_note = " (at/near cap)" if count >= DEFAULT_SOURCE_CAP * 0.9 else ""
        print(f"  {source}: {count}{cap_note}")
