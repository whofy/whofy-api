import re
import time
from datetime import datetime, timezone, timedelta

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query, Request
from fetch_api.limiter import limiter

from db.mongo import get_async_db
from listings.shared.normalize import strip_html

router = APIRouter()

# Short-TTL in-memory cache for the dropdown endpoints
# (/api/locations, /api/sources). These run distinct() over
# ~49k jobs on every call and return data that only changes when ingestion
# runs (once a day) — a 5-minute stale window is invisible to users.
_DROPDOWN_CACHE: dict[str, tuple[float, object]] = {}
_DROPDOWN_TTL_SECONDS = 300


def _cache_get(key: str):
    entry = _DROPDOWN_CACHE.get(key)
    if entry and entry[0] > time.monotonic():
        return entry[1]
    return None


def _cache_set(key: str, value) -> None:
    _DROPDOWN_CACHE[key] = (time.monotonic() + _DROPDOWN_TTL_SECONDS, value)

_TAG_RE = re.compile(r"<[a-zA-Z/][^>]*>")

_SPAM_RE = re.compile(
    r"(?:please mention the word|tag [A-Za-z0-9+/=]{10,}|"
    r"this is a beta feature to avoid spam|"
    r"companies can search these words)",
    re.IGNORECASE,
)


def _clean_description(desc: str) -> str:
    if not desc:
        return desc
    if _TAG_RE.search(desc):
        desc = strip_html(desc)
    lines = desc.split("\n")
    cleaned = [l for l in lines if not _SPAM_RE.search(l)]
    return "\n".join(cleaned).strip()


def serialize_job(doc: dict, matched_skills: list[str] | None = None) -> dict:
    # Logo resolution — single source of truth, no guessing:
    #   1. Source-provided direct URL (RemoteOK's company_logo field)
    #   2. Google favicon of a source-provided real domain
    #   3. null → frontend renders a colored-letter fallback
    logo_url = doc.get("logo_url")
    if not logo_url:
        domain = doc.get("company_domain")
        if domain:
            logo_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"

    title = doc.get("title", "")
    location = doc.get("location", "Not specified")
    desc = _clean_description(doc.get("description", ""))
    # work_type, experience_level, and required_skills are now strictly guaranteed by ingestion.
    work_type = doc.get("work_type")
    experience = doc.get("experience_level")
    required_skills = doc.get("required_skills", [])
    
    posted_at = doc.get("posted_at")
    
    job = {
        "id": str(doc["_id"]),
        "title": title,
        "company": doc.get("company", ""),
        "location": location,
        "description": desc,
        "applyUrl": doc.get("apply_url", ""),
        "postedAt": posted_at.isoformat() if isinstance(posted_at, datetime) else posted_at,
        "source": doc.get("source", ""),
        "workType": work_type,
        "experience": experience,
        "requiredSkills": required_skills,
        "logoUrl": logo_url,
    }
    if matched_skills is not None:
        job["matchedSkills"] = matched_skills
    return job


def _split_param(val: str, sep: str = r"[,|]") -> list[str]:
    return [s.strip() for s in re.split(sep, val) if s.strip()]


def _posted_cutoff(posted: str):
    mapping = {"today": 1, "week": 7, "month": 30}
    days = mapping.get(posted)
    if days is None:
        return None
    return datetime.now(timezone.utc) - timedelta(days=days)


def _build_filter(
    source: str | None,
    location: str | None,
    work_type: str | None = None,
    experience: str | None = None,
    posted: str | None = None,
) -> dict:
    filt = {}
    # Any clause needing its own $or is collected here and emitted as a single
    # $and. Assigning filt["$or"] directly means the second such clause
    # silently overwrites the first — both location and posted need one.
    and_clauses: list[dict] = []

    if source:
        vals = _split_param(source)
        if vals:
            filt["source"] = {"$in": vals} if len(vals) > 1 else vals[0]
    if location:
        vals = _split_param(location, sep=r"\|")
        if vals:
            if len(vals) == 1:
                filt["location"] = {"$regex": re.escape(vals[0]), "$options": "i"}
            else:
                and_clauses.append({
                    "$or": [{"location": {"$regex": re.escape(v), "$options": "i"}} for v in vals]
                })
    if work_type:
        vals = _split_param(work_type)
        if vals:
            filt["work_type"] = {"$in": vals} if len(vals) > 1 else vals[0]
    if experience:
        vals = _split_param(experience)
        if vals:
            filt["experience_level"] = {"$in": vals} if len(vals) > 1 else vals[0]
    if posted:
        cutoff = _posted_cutoff(posted)
        if cutoff:
            # Lever doesn't expose a post date, so its jobs store posted_at as
            # None — and {"$gte": cutoff} never matches null. Filtering on
            # posted_at alone made every Lever job disappear the moment a user
            # picked any Posted option. For undated jobs we fall back to
            # added_at (when we first ingested it), which is a fair proxy for
            # "new" and is indexed.
            and_clauses.append({
                "$or": [
                    {"posted_at": {"$gte": cutoff}},
                    {"posted_at": None, "added_at": {"$gte": cutoff}},
                ]
            })

    if and_clauses:
        filt["$and"] = and_clauses
    return filt


@router.get("/api/matches")
@limiter.limit("30/minute")
async def get_matches(
    request: Request,
    limit: int = Query(50, ge=1, le=1000),
    skip: int = Query(0, ge=0),
    skills: str = Query(None, description="Comma-separated skills to rank matches by"),
    source: str = Query(None),
    location: str = Query(None),
    type: str = Query(None, description="Comma-separated work types (Remote/Hybrid/On-site)"),
    experience: str = Query(None, description="Comma-separated experience levels"),
    posted: str = Query(None, description="Date range: today, week, or month"),
):
    db = get_async_db()
    skill_list = [s.strip() for s in skills.split(",") if s.strip()] if skills else []
    base_filter = _build_filter(source, location, type, experience, posted)

    if not skill_list:
        total = await db.jobs.count_documents(base_filter)
        docs = await db.jobs.find(base_filter).sort([("posted_at", -1), ("_id", 1)]).skip(skip).to_list(length=limit)
        return {
            "jobs": [serialize_job(doc) for doc in docs],
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    # $text is a loose fuzzy match (stemming), so it can surface jobs that
    # share only a common English word (e.g. "storage", "design"). Require
    # at least one skill to appear as a real substring in title/description
    # before returning the job — otherwise a Go-only role can leak into a
    # React/Python match list because its description says "storage".
    scored_stage = [
        {"$match": {**base_filter, "$text": {"$search": " ".join(skill_list)}}},
        {"$addFields": {
            "matched_skills": {
                "$filter": {
                    "input": skill_list,
                    "as": "skill",
                    "cond": {
                        "$or": [
                            {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$title", ""]}}, {"$toLower": "$$skill"}]}, 0]},
                            {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$description", ""]}}, {"$toLower": "$$skill"}]}, 0]}
                        ]
                    }
                }
            }
        }},
        {"$addFields": {"match_count": {"$size": "$matched_skills"}}},
        {"$match": {"match_count": {"$gte": 1}}},
    ]

    facet_stage = {
        "$facet": {
            "docs": [
                {"$sort": {"match_count": -1, "last_seen_at": -1, "_id": 1}},
                {"$skip": skip},
                {"$limit": limit},
            ],
            "total": [{"$count": "value"}],
        }
    }

    facet = await db.jobs.aggregate(scored_stage + [facet_stage], allowDiskUse=True).to_list(length=1)
    result = facet[0] if facet else {"docs": [], "total": []}
    docs = result["docs"]
    total = result["total"][0]["value"] if result["total"] else 0

    return {
        "jobs": [serialize_job(doc, doc.get("matched_skills", [])) for doc in docs],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/api/search")
@limiter.limit("30/minute")
async def search_jobs(
    request: Request,
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(15, ge=1, le=200),
    skip: int = Query(0, ge=0),
    source: str = Query(None),
    location: str = Query(None),
    type: str = Query(None),
    experience: str = Query(None),
    posted: str = Query(None),
):
    db = get_async_db()
    base_filter = _build_filter(source, location, type, experience, posted)

    # Tokenize the query for title-anchored matching.
    tokens = re.findall(r"[a-z0-9+#.]+", q.lower())
    if not tokens:
        query = {**base_filter, "$text": {"$search": q}}
        total = await db.jobs.count_documents(query)
        docs = await db.jobs.find(query).skip(skip).limit(limit).to_list(length=limit)
        return {
            "jobs": [serialize_job(doc) for doc in docs],
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    # Ranking rules:
    #   - At least one query token must appear in the title OR in the job's
    #     required_skills list. Description-only hits are noise ("developer"
    #     mentioned in a Customer Relationship Manager paragraph).
    #   - For 3+ word queries, require a majority of tokens somewhere in
    #     title/skills so we don't over-tighten multi-word searches.
    min_total_matches = 1 if len(tokens) <= 2 else max(2, len(tokens) - 1)

    # Reusable Mongo expression: does the input token appear (case-insensitive)
    # as a substring in any element of $required_skills?
    def _token_in_skills():
        return {
            "$anyElementTrue": {
                "$map": {
                    "input": {"$ifNull": ["$required_skills", []]},
                    "as": "sk",
                    "in": {"$gte": [{"$indexOfCP": [{"$toLower": "$$sk"}, {"$toLower": "$$token"}]}, 0]}
                }
            }
        }

    scored_stage = [
        {"$match": {**base_filter, "$text": {"$search": q}}},
        {"$addFields": {
            "score": {"$meta": "textScore"},
            "title_hits": {
                "$size": {
                    "$filter": {
                        "input": tokens,
                        "as": "token",
                        "cond": {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$title", ""]}}, {"$toLower": "$$token"}]}, 0]}
                    }
                }
            },
            "skill_hits": {
                "$size": {
                    "$filter": {
                        "input": tokens,
                        "as": "token",
                        "cond": _token_in_skills()
                    }
                }
            },
            "total_hits": {
                "$size": {
                    "$filter": {
                        "input": tokens,
                        "as": "token",
                        "cond": {
                            "$or": [
                                {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$title", ""]}}, {"$toLower": "$$token"}]}, 0]},
                                _token_in_skills(),
                            ]
                        }
                    }
                }
            }
        }},
        # Must match title OR skills (not description). And enough tokens total.
        {"$match": {"total_hits": {"$gte": min_total_matches}}},
    ]

    facet_stage = {
        "$facet": {
            "docs": [
                {"$sort": {"title_hits": -1, "skill_hits": -1, "total_hits": -1, "score": -1, "_id": 1}},
                {"$skip": skip},
                {"$limit": limit},
            ],
            "total": [{"$count": "value"}],
        }
    }

    facet = await db.jobs.aggregate(scored_stage + [facet_stage], allowDiskUse=True).to_list(length=1)
    result = facet[0] if facet else {"docs": [], "total": []}
    docs = result["docs"]
    total = result["total"][0]["value"] if result["total"] else 0

    if not docs and skip == 0:
        # Fallback: same rule but only require ANY token to hit title or skills
        # (drops the min_total_matches gate). Description matches still excluded.
        fb_stage = [
            {"$match": {**base_filter, "$text": {"$search": q}}},
            {"$addFields": {
                "score": {"$meta": "textScore"},
                "title_hits": {
                    "$size": {
                        "$filter": {
                            "input": tokens,
                            "as": "token",
                            "cond": {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$title", ""]}}, {"$toLower": "$$token"}]}, 0]}
                        }
                    }
                },
                "skill_hits": {
                    "$size": {
                        "$filter": {
                            "input": tokens,
                            "as": "token",
                            "cond": _token_in_skills()
                        }
                    }
                },
            }},
            {"$match": {"$or": [{"title_hits": {"$gte": 1}}, {"skill_hits": {"$gte": 1}}]}},
        ]
        fb_facet = {
            "$facet": {
                "docs": [
                    {"$sort": {"title_hits": -1, "skill_hits": -1, "score": -1, "_id": 1}},
                    {"$skip": skip},
                    {"$limit": limit},
                ],
                "total": [{"$count": "value"}],
            }
        }
        fb = await db.jobs.aggregate(fb_stage + [fb_facet], allowDiskUse=True).to_list(length=1)
        fb_result = fb[0] if fb else {"docs": [], "total": []}
        docs = fb_result["docs"]
        total = fb_result["total"][0]["value"] if fb_result["total"] else 0

    return {
        "jobs": [serialize_job(doc) for doc in docs],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


_JUNK_LOC_RE = re.compile(
    r"https?:|&#|\.com|\.io|\.dev|\.net\b|you&#|we&#|I&#|^n/a$"
    r"|[{}()\[\]]|\.{2,}|[?!]"
    r"|you'll|we're|you're|i'm|i don"
    r"|&amp|&quot|&lt|&gt|CRUD|Multiple "
    r"|^\.NET$| OR | & | EMEA"
    r"|^[A-Z]{2,4}\.[A-Z]{2}\.",
    re.IGNORECASE,
)


def _is_valid_location(loc: str) -> bool:
    if not loc or len(loc) < 2 or len(loc) > 60:
        return False
    if "remote" in loc.lower():
        return False
    if _JUNK_LOC_RE.search(loc):
        return False
    if sum(1 for c in loc if c == ' ') > 8:
        return False
    return True


@router.get("/api/locations")
@limiter.limit("10/minute")
async def get_locations(request: Request):
    cached = _cache_get("locations")
    if cached is not None:
        return cached

    db = get_async_db()
    raw = [v for v in await db.jobs.distinct("location") if v and v.strip()]
    locations = set()
    for loc in raw:
        if ";" in loc:
            for part in loc.split(";"):
                part = part.strip()
                if _is_valid_location(part):
                    locations.add(part)
        elif _is_valid_location(loc):
            locations.add(loc)
    result = sorted(locations)
    _cache_set("locations", result)
    return result


@router.get("/api/sources")
@limiter.limit("10/minute")
async def get_sources(request: Request):
    cached = _cache_get("sources")
    if cached is not None:
        return cached

    db = get_async_db()
    values = [v for v in await db.jobs.distinct("source") if v and v.strip()]
    result = sorted(values)
    _cache_set("sources", result)
    return result


@router.get("/api/jobs/{job_id}")
@limiter.limit("60/minute")
async def get_job(job_id: str, request: Request):
    try:
        oid = ObjectId(job_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid job id")

    db = get_async_db()
    doc = await db.jobs.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")

    return serialize_job(doc)
