import re
from concurrent.futures import ProcessPoolExecutor
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
from listings.shared.retention import RETENTION_DAYS

DB_NAME = "whofy"
JOBS_COLLECTION = "jobs"
REJECTIONS_COLLECTION = "ingestion_rejections"
DEFAULT_SOURCE_CAP = 20000

# Capped collection: auto-drops oldest docs when full. Sized to hold roughly
# the last 500 rejections. Debugging tool only — safe to lose old rows.
_REJECTIONS_CAP_BYTES = 5 * 1024 * 1024  # 5 MB
_REJECTIONS_CAP_DOCS = 500


def _log_rejection(db, source: str, job: dict, error: Exception) -> None:
    """Persist a schema-rejected payload so we can inspect it later. Writes
    are best-effort — a logging failure must never break ingestion."""
    try:
        db[REJECTIONS_COLLECTION].insert_one({
            "source": source,
            "source_job_id": job.get("source_job_id"),
            "title": job.get("title"),
            "company": job.get("company"),
            "error_type": type(error).__name__,
            "error_message": str(error)[:2000],
            "raw_payload": job,
            "rejected_at": datetime.now(timezone.utc),
        })
    except Exception as log_err:
        print(f"[{source}] failed to log rejection: {log_err}")


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


_TOKEN_SPLIT_RE = re.compile(r"[;,]\s*")
_COMPANY_SORT_LEADING_RE = re.compile(r"^[^0-9A-Za-z]+")


def _normalize_company_sort(company: str) -> str:
    """Sort key for the "Company (A-Z)" order.

    Users expect A-Z to mean letters first, alphabetically, case-insensitive.
    Raw ASCII sort gets three things wrong:

      1. Leading punctuation ("*Strello Health") lands before real names
         because "*" (0x2A) < letters.
      2. Uppercase and lowercase sort into separate blocks ("Zoom" before
         "apple" because "Z" (0x5A) < "a" (0x61)).
      3. Digit-starting names ("037 PitchBook", "1-800-flowers") land ahead
         of "A..." because digits (0x30-0x39) < letters.

    Fixes:
      - Strip leading non-alphanumerics.
      - Lowercase so case doesn't fragment the alphabet.
      - Prefix digit-starting names with "~" (0x7E, after all lowercase
         letters) so they sort at the end instead of the top.
    """
    if not isinstance(company, str):
        return ""
    stripped = _COMPANY_SORT_LEADING_RE.sub("", company).strip().lower()
    if not stripped:
        return company.strip().lower()
    if stripped[0].isdigit():
        return "~" + stripped
    return stripped


def _tokenize_location(location: str) -> list[str]:
    """Split a normalized location string into a searchable token array.

    Powers indexed filtering on /api/matches (see fetch_api/jobs.py). Each
    piece separated by comma or semicolon becomes one lowercase token:

        "Bengaluru, India"                       → ["bengaluru", "india"]
        "Berlin, Germany; London, United Kingdom" → ["berlin", "germany",
                                                    "london", "united kingdom"]
        "Remote"                                  → ["remote"]

    Querying with $all against this array is an indexed lookup — far faster
    than the previous case-insensitive regex over the raw `location` field,
    and correct for compound picks like "Bengaluru, India" (which requires
    both tokens present) as well as broad picks like just "India".
    """
    if not location:
        return []
    seen: set[str] = set()
    tokens: list[str] = []
    for part in _TOKEN_SPLIT_RE.split(location):
        part = part.strip().lower()
        if part and part not in seen:
            seen.add(part)
            tokens.append(part)
    return tokens


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
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
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


_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _posted_sort_key(job: dict) -> datetime:
    """Sort key for the source-cap truncation in save_jobs.

    This runs BEFORE Pydantic validation, so `posted_at` may still be any of
    three shapes: a real datetime (Greenhouse/Ashby/Adzuna/RemoteOK/Himalayas),
    an ISO string (Workday/WWR), or None (Lever, and any source that couldn't
    parse its own date).

    The previous key was `j.get("posted_at") or ""`, which substituted a str
    for None and then asked Python to order a datetime against a str —
    TypeError, which escaped save_jobs, failed the whole source, and (because
    run_ingestion skips cleanup when any source fails) took down retention
    enforcement and the remaining workflow steps with it.

    Undated jobs sort last; they're kept only if there's room under the cap.
    """
    pa = job.get("posted_at")
    if isinstance(pa, str):
        try:
            pa = datetime.fromisoformat(pa.replace("Z", "+00:00"))
        except ValueError:
            return _EPOCH
    if isinstance(pa, datetime):
        return pa if pa.tzinfo else pa.replace(tzinfo=timezone.utc)
    return _EPOCH


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
        # Precomputed at ingest so the API can filter by exact indexed
        # tokens instead of a case-insensitive regex on 65k+ rows.
        job["location_tokens"] = _tokenize_location(job.get("location", ""))
        # Trim company — leading/trailing whitespace corrupts "Company A-Z"
        # sort because " Foo" (0x20) sorts before "*Foo" (0x2A) etc.
        raw_company = job.get("company")
        if isinstance(raw_company, str):
            job["company"] = raw_company.strip()
        # Sort key that strips leading punctuation so "*Strello Health" lands
        # under "S" and ". Crane Worldwide Logistics ." lands under "C".
        # Display still uses the untouched `company`.
        job["company_sort"] = _normalize_company_sort(job.get("company", ""))

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
        jobs = sorted(jobs, key=_posted_sort_key, reverse=True)[:cap]
        capped = True

    client = get_client()
    db = client[DB_NAME]
    collection = db[JOBS_COLLECTION]

    # NOTE: there was a "skip jobs already ingested from another source" query
    # here. It was unreachable by construction — _fingerprint() embeds the
    # source name in the fingerprint, so {"fingerprint": {"$in": ...},
    # "source": {"$ne": source}} can never match. It always returned empty
    # while shipping an $in list of up to `cap` strings to Atlas on every save.
    # Cross-source dedup is handled properly by canonical_fingerprint +
    # pipeline/dedupe_jobs.py.

    # Real datetime — NOT `.isoformat()`. Pymongo serializes datetime → BSON
    # Date; a string would land as BSON String. cleanup_expired_jobs then
    # does {"last_seen_at": {"$lt": <datetime>}}, and in BSON sort order
    # every String is less than every Date — so a single stray string field
    # would make the cleanup match every job in the collection. See
    # test_datetime_types.py for the guard test that pins this invariant.
    now = datetime.now(timezone.utc)

    from models.job import Job
    operations = []
    schema_rejected = 0
    for job in jobs:
        job["last_seen_at"] = now
        job["lang_checked"] = True

        if "added_at" not in job:
            job["added_at"] = now

        try:
            validated_job = Job.model_validate(job).model_dump(by_alias=True)
        except Exception as e:
            schema_rejected += 1
            _log_rejection(db, source, job, e)
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

    # save_jobs sets lang_checked=True on every write, so the only rows this
    # can ever match are legacy docs from before that was true. Check the count
    # first — once they're drained this is a single cheap query per run instead
    # of spinning up an 8-process pool to scan for nothing.
    pending = collection.count_documents({"lang_checked": {"$ne": True}})
    if pending == 0:
        return 0

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


def cleanup_expired_jobs(expiry_days: int = RETENTION_DAYS) -> int:
    """Delete jobs on two conditions (whichever matches):
      1. `last_seen_at < cutoff` — source removed the posting >expiry_days ago.
      2. `posted_at < cutoff` — job was originally posted >expiry_days ago.

    #2 is critical for staying on Atlas free tier. Without it, jobs still
    live on their source keep bumping `last_seen_at` and never age out,
    which lets the DB grow to the retention floor of every source combined.
    With #2, the DB is bounded to "jobs posted in the last N days" regardless
    of how long the source keeps the listing open.

    Jobs without a `posted_at` (some Lever postings) are only affected by
    condition #1."""
    client = get_client()
    db = client[DB_NAME]
    collection = db[JOBS_COLLECTION]

    cutoff = datetime.now(timezone.utc) - timedelta(days=expiry_days)
    result = collection.delete_many({
        "$or": [
            {"last_seen_at": {"$lt": cutoff}},
            {"posted_at":    {"$lt": cutoff}},
        ]
    })
    return result.deleted_count


# Fields covered by the `$text` index powering /api/search and the skill
# ranking in /api/matches.
#
# `description` used to be in here. It cost 253 MB of a 283 MB index budget —
# 3.5x the size of the entire jobs collection — because a text index stores an
# entry per meaningful word, and job descriptions are long. It bought very
# little: /api/search already discards any hit that only matched the
# description ("Description-only hits are noise"), so most of what that index
# produced was candidates the very next stage threw away.
#
# `required_skills` covers the same ground at a fraction of the size: it's the
# skill vocabulary already extracted from the title and description at ingest.
TEXT_INDEX_FIELDS = ("title", "required_skills")


def _existing_text_index(collection):
    """Return (name, {fields}) for the collection's text index, or None.

    A text index reports its covered fields in `weights`, not in `key` — `key`
    is always {_fts: 'text', _ftsx: 1}.
    """
    for idx in collection.list_indexes():
        weights = idx.get("weights")
        if weights:
            return idx["name"], set(weights.keys())
    return None


def _ensure_text_index(collection) -> None:
    """Create the text index, replacing it if it covers the wrong fields.

    MongoDB allows only ONE text index per collection, so there is no way to
    build the replacement alongside the old one and swap atomically. The drop
    has to come first, which leaves a window — however brief — where `$text`
    queries fail with "text index required for $text query". Both /api/search
    and the skill branch of /api/matches error during that window.

    That window is why this runs from ensure_indexes at the start of
    ingestion (00:00 UTC) rather than on API startup.
    """
    desired = set(TEXT_INDEX_FIELDS)
    existing = _existing_text_index(collection)

    if existing and existing[1] == desired:
        return

    if existing:
        name, fields = existing
        print(
            f"Text index '{name}' covers {sorted(fields)}, expected {sorted(desired)} — "
            f"replacing. $text queries will fail until the new index is built."
        )
        collection.drop_index(name)

    collection.create_index([(f, "text") for f in TEXT_INDEX_FIELDS])
    print(f"Text index created on {sorted(desired)}.")


def ensure_indexes():
    client = get_client()
    db = client[DB_NAME]
    collection = db[JOBS_COLLECTION]

    collection.create_index([("source", 1), ("source_job_id", 1)], unique=True)
    collection.create_index([("posted_at", -1), ("_id", 1)])
    collection.create_index([("last_seen_at", -1)])
    collection.create_index([("added_at", -1)])
    _ensure_text_index(collection)
    collection.create_index([("work_type", 1)])
    collection.create_index([("experience_level", 1)])
    # Location and source filters used to COLLSCAN the whole jobs collection
    # on every hit — location auto-applies from the user's resume, so it's on
    # the hot path for nearly every session. Multikey index on the token
    # array powers indexed $all lookups (see _tokenize_location).
    collection.create_index([("location_tokens", 1)])
    collection.create_index([("source", 1)])
    # Supports the server-side "Company (A–Z)" sort on /api/matches and
    # /api/search. Without this, sorting by company COLLSCANs the whole
    # jobs collection on every page click.
    # NOTE: a plain ("company", 1) index used to live here. The A-Z sort moved
    # to `company_sort` (which strips leading punctuation), leaving the old one
    # unread — confirmed by $indexStats: 0 accesses, 2.4 MB, updated on every
    # write. Dropped by pipeline/migrate_text_index.py.
    collection.create_index([("company_sort", 1), ("_id", 1)])
    collection.create_index("canonical_fingerprint")  # for cross-source dedup grouping

    saved_jobs_col = db["saved_jobs"]
    saved_jobs_col.create_index([("user_id", 1), ("job_id", 1)], unique=True)
    saved_jobs_col.create_index([("user_id", 1), ("saved_at", -1)])

    # Capped rejections collection — first run creates it, later runs are no-ops.
    if REJECTIONS_COLLECTION not in db.list_collection_names():
        try:
            db.create_collection(
                REJECTIONS_COLLECTION,
                capped=True,
                size=_REJECTIONS_CAP_BYTES,
                max=_REJECTIONS_CAP_DOCS,
            )
        except Exception as e:
            print(f"Could not create capped {REJECTIONS_COLLECTION}: {e}")
    db[REJECTIONS_COLLECTION].create_index([("rejected_at", -1)])
    db[REJECTIONS_COLLECTION].create_index([("source", 1), ("rejected_at", -1)])

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
