import re
from datetime import datetime, timezone, timedelta

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query, Request
from fetch_api.limiter import limiter

from db.mongo import get_async_db
from listings.shared.enrich import detect_experience, detect_work_type, extract_required_skills
from listings.shared.normalize import strip_html

router = APIRouter()

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


def _guess_domain(company: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "", company.lower())
    if not slug:
        return ""
    return f"{slug}.com"


def serialize_job(doc: dict, matched_skills: list[str] | None = None) -> dict:
    logo_url = doc.get("logo_url")
    if not logo_url:
        domain = doc.get("company_domain", "")
        if not domain:
            domain = _guess_domain(doc.get("company", ""))
        logo_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128" if domain else None

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
    company: str | None,
    location: str | None,
    work_type: str | None = None,
    experience: str | None = None,
    posted: str | None = None,
) -> dict:
    filt = {}
    if source:
        vals = _split_param(source)
        if vals:
            filt["source"] = {"$in": vals} if len(vals) > 1 else vals[0]
    if company:
        vals = _split_param(company)
        if vals:
            filt["company"] = {"$in": vals} if len(vals) > 1 else vals[0]
    if location:
        vals = _split_param(location, sep=r"\|")
        if vals:
            if len(vals) == 1:
                filt["location"] = {"$regex": re.escape(vals[0]), "$options": "i"}
            else:
                filt["$or"] = [{"location": {"$regex": re.escape(v), "$options": "i"}} for v in vals]
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
            filt["posted_at"] = {"$gte": cutoff}
    return filt


@router.get("/api/matches")
@limiter.limit("30/minute")
async def get_matches(
    request: Request,
    limit: int = Query(50, ge=1, le=1000),
    skip: int = Query(0, ge=0),
    skills: str = Query(None, description="Comma-separated skills to rank matches by"),
    source: str = Query(None),
    company: str = Query(None),
    location: str = Query(None),
    type: str = Query(None, description="Comma-separated work types (Remote/Hybrid/On-site)"),
    experience: str = Query(None, description="Comma-separated experience levels"),
    posted: str = Query(None, description="Date range: today, week, or month"),
):
    db = get_async_db()
    skill_list = [s.strip() for s in skills.split(",") if s.strip()] if skills else []
    base_filter = _build_filter(source, company, location, type, experience, posted)

    if not skill_list:
        total = await db.jobs.count_documents(base_filter)
        docs = await db.jobs.find(base_filter).sort([("posted_at", -1), ("_id", 1)]).skip(skip).to_list(length=limit)
        return {
            "jobs": [serialize_job(doc) for doc in docs],
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    query = {**base_filter, "$text": {"$search": " ".join(skill_list)}}
    total = await db.jobs.count_documents(query)

    pipeline = [
        {"$match": query},
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
        {"$sort": {"match_count": -1, "last_seen_at": -1, "_id": 1}},
        {"$skip": skip},
        {"$limit": limit}
    ]

    docs = await db.jobs.aggregate(pipeline, allowDiskUse=True).to_list(length=limit)

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
    limit: int = Query(200, ge=1, le=1000),
    skip: int = Query(0, ge=0),
):
    db = get_async_db()
    
    # Tokenize the query for strict matching
    tokens = re.findall(r"[a-z0-9+#.]+", q.lower())
    if not tokens:
        docs = await db.jobs.find({"$text": {"$search": q}}).skip(skip).limit(limit).to_list(length=limit)
        return [serialize_job(doc) for doc in docs]

    min_matches = len(tokens) if len(tokens) <= 3 else len(tokens) - 1

    pipeline = [
        {"$match": {"$text": {"$search": q}}},
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
            "total_hits": {
                "$size": {
                    "$filter": {
                        "input": tokens,
                        "as": "token",
                        "cond": {
                            "$or": [
                                {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$title", ""]}}, {"$toLower": "$$token"}]}, 0]},
                                {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$description", ""]}}, {"$toLower": "$$token"}]}, 0]}
                            ]
                        }
                    }
                }
            }
        }},
        {"$match": {"total_hits": {"$gte": min_matches}}},
        {"$sort": {"title_hits": -1, "total_hits": -1, "score": -1, "_id": 1}},
        {"$skip": skip},
        {"$limit": limit}
    ]

    docs = await db.jobs.aggregate(pipeline, allowDiskUse=True).to_list(length=limit)
    if not docs:
        # Fallback to pure text search if strict matching yielded nothing
        docs = await db.jobs.find({"$text": {"$search": q}}, {"score": {"$meta": "textScore"}}).sort([("score", {"$meta": "textScore"})]).skip(skip).limit(limit).to_list(length=limit)
        
    return [serialize_job(doc) for doc in docs]


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
    return sorted(locations)


@router.get("/api/companies")
@limiter.limit("10/minute")
async def get_companies(request: Request):
    db = get_async_db()
    values = [v for v in await db.jobs.distinct("company") if v and v.strip()]
    return sorted(values)


@router.get("/api/sources")
@limiter.limit("10/minute")
async def get_sources(request: Request):
    db = get_async_db()
    values = [v for v in await db.jobs.distinct("source") if v and v.strip()]
    return sorted(values)


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
