import re

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query

from db.mongo import get_db
from matching.ranker import rank_by_skills, rank_by_search_query
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
    domain = doc.get("company_domain", "")
    if not domain:
        domain = _guess_domain(doc.get("company", ""))

    title = doc.get("title", "")
    location = doc.get("location", "Not specified")
    # work_type/experience_level/required_skills are computed once at
    # ingestion time from the FULL (untruncated) posting text and stored on
    # the doc (see sources/shared/enrich.py) — required_skills is already
    # baked into the stored description there too, so filtering is a plain
    # Mongo query and search indexes the skill terms. Fallback to on-the-fly
    # detection (against the short display text) only covers stray docs that
    # somehow bypassed ingestion.
    desc = _clean_description(doc.get("description", ""))
    work_type = doc.get("work_type") or detect_work_type(title, location, desc)
    experience = doc.get("experience_level") or detect_experience(title, desc)
    required_skills = doc.get("required_skills")
    if required_skills is None:
        required_skills = extract_required_skills(title, desc)

    job = {
        "id": str(doc["_id"]),
        "title": title,
        "company": doc.get("company", ""),
        "location": location,
        "description": desc,
        "applyUrl": doc.get("apply_url", ""),
        "postedAt": doc.get("posted_at") or None,
        "source": doc.get("source", ""),
        "workType": work_type,
        "experience": experience,
        "requiredSkills": required_skills,
        "logoUrl": f"https://www.google.com/s2/favicons?domain={domain}&sz=128" if domain else None,
    }
    if matched_skills is not None:
        job["matchedSkills"] = matched_skills
    return job


def _split_param(val: str) -> list[str]:
    return [s.strip() for s in re.split(r"[,|]", val) if s.strip()]


def _build_filter(
    source: str | None,
    company: str | None,
    location: str | None,
    work_type: str | None = None,
    experience: str | None = None,
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
        vals = _split_param(location)
        if vals:
            filt["location"] = {"$in": vals} if len(vals) > 1 else vals[0]
    if work_type:
        vals = _split_param(work_type)
        if vals:
            filt["work_type"] = {"$in": vals} if len(vals) > 1 else vals[0]
    if experience:
        vals = _split_param(experience)
        if vals:
            filt["experience_level"] = {"$in": vals} if len(vals) > 1 else vals[0]
    return filt


@router.get("/api/matches")
def get_matches(
    limit: int = Query(50, ge=1, le=1000),
    skip: int = Query(0, ge=0),
    skills: str = Query(None, description="Comma-separated skills to rank matches by"),
    source: str = Query(None),
    company: str = Query(None),
    location: str = Query(None),
    type: str = Query(None, description="Comma-separated work types (Remote/Hybrid/On-site)"),
    experience: str = Query(None, description="Comma-separated experience levels"),
):
    db = get_db()
    skill_list = [s.strip() for s in skills.split(",") if s.strip()] if skills else []
    base_filter = _build_filter(source, company, location, type, experience)

    if not skill_list:
        total = db.jobs.count_documents(base_filter)
        if not base_filter:
            pipeline = [{"$sample": {"size": limit}}]
            docs = list(db.jobs.aggregate(pipeline))
        else:
            docs = list(db.jobs.find(base_filter).sort("posted_at", -1).skip(skip).limit(limit))
        return {
            "jobs": [serialize_job(doc) for doc in docs],
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    query = {**base_filter, "$text": {"$search": " ".join(skill_list)}}
    total = db.jobs.count_documents(query)
    candidates = list(
        db.jobs.find(query, {"score": {"$meta": "textScore"}})
        .sort([("score", {"$meta": "textScore"})])
        .limit(limit * 3)
    )

    scored = rank_by_skills(candidates, skill_list)
    page = scored[skip:skip + limit]

    return {
        "jobs": [serialize_job(doc, matched) for doc, matched in page],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/api/search")
def search_jobs(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(200, ge=1, le=1000),
):
    db = get_db()
    candidates = list(
        db.jobs.find(
            {"$text": {"$search": q}},
            {"score": {"$meta": "textScore"}},
        )
        .sort([("score", {"$meta": "textScore"})])
        .limit(max(limit * 5, 500))
    )
    final_docs = rank_by_search_query(candidates, q)
    return [serialize_job(doc) for doc in final_docs[:limit]]


@router.get("/api/locations")
def get_locations():
    db = get_db()
    values = [v for v in db.jobs.distinct("location") if v and v.strip()]
    return sorted(values)


@router.get("/api/companies")
def get_companies():
    db = get_db()
    values = [v for v in db.jobs.distinct("company", {"company_domain": {"$exists": True, "$ne": ""}}) if v and v.strip()]
    return sorted(values)


@router.get("/api/sources")
def get_sources():
    db = get_db()
    values = [v for v in db.jobs.distinct("source") if v and v.strip()]
    return sorted(values)


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    try:
        oid = ObjectId(job_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid job id")

    db = get_db()
    doc = db.jobs.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")

    return serialize_job(doc)
