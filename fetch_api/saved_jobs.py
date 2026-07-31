from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db.mongo import get_db
from fetch_api.jobs import serialize_job
from fetch_api.auth import get_current_user

router = APIRouter()


class SaveJobRequest(BaseModel):
    job_id: str


@router.post("/api/saved-jobs")
def save_job(req: SaveJobRequest, user_id: str = Depends(get_current_user)):
    db = get_db()
    existing = db.saved_jobs.find_one({"user_id": user_id, "job_id": req.job_id})
    if existing:
        return {"status": "already_saved"}

    try:
        job_doc = db.jobs.find_one({"_id": ObjectId(req.job_id)})
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    if not job_doc:
        raise HTTPException(status_code=404, detail="Job not found")

    db.saved_jobs.insert_one({
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
def unsave_job(job_id: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    result = db.saved_jobs.delete_one({"user_id": user_id, "job_id": job_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Saved job not found")
    return {"status": "removed"}


@router.get("/api/saved-jobs")
def get_saved_jobs(user_id: str = Depends(get_current_user)):
    db = get_db()
    saved_docs = list(db.saved_jobs.find({"user_id": user_id}).sort("saved_at", -1))

    jobs = []
    for saved in saved_docs:
        try:
            oid = ObjectId(saved["job_id"])
        except InvalidId:
            continue

        job_doc = db.jobs.find_one({"_id": oid})
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
def get_saved_job_ids(user_id: str = Depends(get_current_user)):
    db = get_db()
    saved_docs = db.saved_jobs.find({"user_id": user_id}, {"job_id": 1})
    return [doc["job_id"] for doc in saved_docs]
