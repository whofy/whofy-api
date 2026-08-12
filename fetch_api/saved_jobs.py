from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from fetch_api.limiter import limiter

from db.mongo import get_async_db
from fetch_api.jobs import serialize_job
from models.job import SavedJob
from fetch_api.auth import get_current_user

router = APIRouter()


class SaveJobRequest(BaseModel):
    job_id: str


@router.post("/api/saved-jobs")
@limiter.limit("30/minute")
async def save_job(req: SaveJobRequest, request: Request, user_id: str = Depends(get_current_user)):
    try:
        oid = ObjectId(req.job_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    db = get_async_db()
    job_doc = await db.jobs.find_one({"_id": oid})
    if not job_doc:
        raise HTTPException(status_code=404, detail="Job not found")

    saved_job_data = {
        "user_id": user_id,
        "job_id": oid,
        "saved_at": datetime.now(timezone.utc),
        "snapshot": {
            "title": job_doc.get("title", ""),
            "company": job_doc.get("company", ""),
            "location": job_doc.get("location", ""),
        }
    }
    validated = SavedJob.model_validate(saved_job_data)
    doc = validated.model_dump(by_alias=True)
    if "_id" in doc and doc["_id"] is None:
        del doc["_id"]

    result = await db.saved_jobs.update_one(
        {"user_id": user_id, "job_id": oid},
        {"$setOnInsert": doc},
        upsert=True,
    )
    return {"status": "saved" if result.upserted_id else "already_saved"}


@router.delete("/api/saved-jobs/{job_id}")
@limiter.limit("30/minute")
async def unsave_job(job_id: str, request: Request, user_id: str = Depends(get_current_user)):
    try:
        oid = ObjectId(job_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    db = get_async_db()
    result = await db.saved_jobs.delete_one({"user_id": user_id, "job_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Saved job not found")
    return {"status": "removed"}


@router.get("/api/saved-jobs")
@limiter.limit("30/minute")
async def get_saved_jobs(
    request: Request,
    user_id: str = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    db = get_async_db()
    total = await db.saved_jobs.count_documents({"user_id": user_id})
    saved_docs = await db.saved_jobs.find({"user_id": user_id}) \
        .sort([("saved_at", -1), ("_id", -1)]) \
        .skip(skip).limit(limit).to_list(length=limit)

    oids = [saved["job_id"] for saved in saved_docs]

    jobs_by_id = {}
    if oids:
        job_docs = await db.jobs.find({"_id": {"$in": oids}}).to_list(length=len(oids))
        jobs_by_id = {doc["_id"]: doc for doc in job_docs}

    jobs = []
    for saved in saved_docs:
        oid = saved["job_id"]
        job_doc = jobs_by_id.get(oid)
        if job_doc:
            job = serialize_job(job_doc)
            job["savedAt"] = saved["saved_at"].isoformat() if isinstance(saved["saved_at"], datetime) else saved["saved_at"]
            job["expired"] = False
        else:
            snapshot = saved.get("snapshot", {})
            job = {
                "id": str(saved["job_id"]),
                "title": snapshot.get("title", "Unknown role"),
                "company": snapshot.get("company", "Unknown company"),
                "location": snapshot.get("location", ""),
                "savedAt": saved["saved_at"].isoformat() if isinstance(saved["saved_at"], datetime) else saved["saved_at"],
                "expired": True,
            }
        jobs.append(job)

    return {"jobs": jobs, "total": total, "skip": skip, "limit": limit}


@router.get("/api/saved-jobs/ids")
@limiter.limit("30/minute")
async def get_saved_job_ids(request: Request, user_id: str = Depends(get_current_user)):
    db = get_async_db()
    saved_docs = await db.saved_jobs.find({"user_id": user_id}, {"job_id": 1}).to_list(length=1000)
    return [str(doc["job_id"]) for doc in saved_docs]
