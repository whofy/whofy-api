from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from fetch_api.limiter import limiter

from db.mongo import get_async_db
from fetch_api.jobs import serialize_job
from fetch_api.auth import get_current_user

router = APIRouter()


class SaveJobRequest(BaseModel):
    job_id: str


@router.post("/api/saved-jobs")
@limiter.limit("30/minute")
async def save_job(req: SaveJobRequest, request: Request, user_id: str = Depends(get_current_user)):
    db = get_async_db()
    existing = await db.saved_jobs.find_one({"user_id": user_id, "job_id": req.job_id})
    if existing:
        return {"status": "already_saved"}

    try:
        job_doc = await db.jobs.find_one({"_id": ObjectId(req.job_id)})
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    if not job_doc:
        raise HTTPException(status_code=404, detail="Job not found")

    await db.saved_jobs.insert_one({
        "user_id": user_id,
        "job_id": req.job_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": {
            "title": job_doc.get("title", ""),
            "company": job_doc.get("company", ""),
            "location": job_doc.get("location", ""),
        },
    })
    return {"status": "saved"}


@router.delete("/api/saved-jobs/{job_id}")
@limiter.limit("30/minute")
async def unsave_job(job_id: str, request: Request, user_id: str = Depends(get_current_user)):
    db = get_async_db()
    result = await db.saved_jobs.delete_one({"user_id": user_id, "job_id": job_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Saved job not found")
    return {"status": "removed"}


@router.get("/api/saved-jobs")
@limiter.limit("30/minute")
async def get_saved_jobs(request: Request, user_id: str = Depends(get_current_user)):
    db = get_async_db()
    saved_docs = await db.saved_jobs.find({"user_id": user_id}).sort("saved_at", -1).to_list(length=1000)

    oids = []
    valid_saved_docs = []
    for saved in saved_docs:
        try:
            oid = ObjectId(saved["job_id"])
            oids.append(oid)
            valid_saved_docs.append((oid, saved))
        except InvalidId:
            continue

    jobs_by_id = {}
    if oids:
        job_docs = await db.jobs.find({"_id": {"$in": oids}}).to_list(length=1000)
        jobs_by_id = {doc["_id"]: doc for doc in job_docs}

    jobs = []
    for oid, saved in valid_saved_docs:
        job_doc = jobs_by_id.get(oid)
        if job_doc:
            job = serialize_job(job_doc)
            job["savedAt"] = saved["saved_at"]
            job["expired"] = False
        else:
            snapshot = saved.get("snapshot", {})
            job = {
                "id": saved["job_id"],
                "title": snapshot.get("title", "Unknown role"),
                "company": snapshot.get("company", "Unknown company"),
                "location": snapshot.get("location", ""),
                "savedAt": saved["saved_at"],
                "expired": True,
            }
        jobs.append(job)

    return jobs


@router.get("/api/saved-jobs/ids")
@limiter.limit("30/minute")
async def get_saved_job_ids(request: Request, user_id: str = Depends(get_current_user)):
    db = get_async_db()
    saved_docs = await db.saved_jobs.find({"user_id": user_id}, {"job_id": 1}).to_list(length=1000)
    return [doc["job_id"] for doc in saved_docs]
