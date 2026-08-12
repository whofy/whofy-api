"""
Tests for the saved-jobs endpoints in fetch_api/saved_jobs.py.

Guards against regressions of the fixes applied on 2026-08-11:
  - F-06 — ObjectId validation returns 400 (not 500) for malformed IDs
  - F-07 — atomic upsert prevents duplicate saves for (user_id, job_id)
  - F-08 — GET returns {jobs, total, skip, limit} envelope; expired-branch `id` is a string
  - N-18 — PyObjectId serializer keeps `job_id` as ObjectId in Mongo so DELETE actually matches
"""

from bson import ObjectId


# ─────────────────────────────────────────────────────────────
# POST /api/saved-jobs — save a job
# ─────────────────────────────────────────────────────────────

async def test_save_new_job_returns_saved_status(client, mock_async_db, seed_job, auth_headers):
    job = await seed_job()
    r = client.post("/api/saved-jobs", json={"job_id": str(job["_id"])}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"status": "saved"}
    assert await mock_async_db.saved_jobs.count_documents({}) == 1


async def test_save_already_saved_returns_already_saved(client, mock_async_db, seed_job, auth_headers):
    """F-07 regression guard — saving the same job twice must NOT create a duplicate row."""
    job = await seed_job()
    body = {"job_id": str(job["_id"])}
    r1 = client.post("/api/saved-jobs", json=body, headers=auth_headers)
    r2 = client.post("/api/saved-jobs", json=body, headers=auth_headers)
    assert r1.json()["status"] == "saved"
    assert r2.json()["status"] == "already_saved"
    assert await mock_async_db.saved_jobs.count_documents({}) == 1


def test_save_invalid_objectid_returns_400_not_500(client, auth_headers):
    """F-06 regression guard — malformed IDs must be 400, not 500."""
    r = client.post("/api/saved-jobs", json={"job_id": "not-a-valid-id"}, headers=auth_headers)
    assert r.status_code == 400
    assert "Invalid job ID" in r.json()["detail"]


def test_save_nonexistent_job_returns_404(client, auth_headers):
    """Valid ObjectId shape but no such document in the jobs collection."""
    fake_id = str(ObjectId())
    r = client.post("/api/saved-jobs", json={"job_id": fake_id}, headers=auth_headers)
    assert r.status_code == 404
    assert "Job not found" in r.json()["detail"]


# ─────────────────────────────────────────────────────────────
# DELETE /api/saved-jobs/{job_id} — unsave
# ─────────────────────────────────────────────────────────────

async def test_unsave_removes_from_db(client, mock_async_db, seed_job, auth_headers):
    """
    N-18 regression guard — after saving then unsaving, the DB row must be gone.
    The old PyObjectId serializer stored job_id as a string, so the DELETE
    query never matched. This test would have caught that immediately.
    """
    job = await seed_job()
    job_id = str(job["_id"])
    client.post("/api/saved-jobs", json={"job_id": job_id}, headers=auth_headers)
    assert await mock_async_db.saved_jobs.count_documents({}) == 1

    r = client.delete(f"/api/saved-jobs/{job_id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"status": "removed"}
    assert await mock_async_db.saved_jobs.count_documents({}) == 0


def test_unsave_invalid_objectid_returns_400_not_500(client, auth_headers):
    """F-06 regression guard."""
    r = client.delete("/api/saved-jobs/not-a-valid-id", headers=auth_headers)
    assert r.status_code == 400
    assert "Invalid job ID" in r.json()["detail"]


def test_unsave_nonexistent_returns_404(client, auth_headers):
    r = client.delete(f"/api/saved-jobs/{ObjectId()}", headers=auth_headers)
    assert r.status_code == 404


# ─────────────────────────────────────────────────────────────
# GET /api/saved-jobs — list with pagination
# ─────────────────────────────────────────────────────────────

def test_list_returns_envelope_shape(client, auth_headers):
    """F-08 regression guard — response must be {jobs, total, skip, limit}, not a bare list."""
    r = client.get("/api/saved-jobs", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"jobs", "total", "skip", "limit"}
    assert body == {"jobs": [], "total": 0, "skip": 0, "limit": 50}


async def test_list_pagination_skip_limit(client, mock_async_db, seed_job, auth_headers):
    """skip and limit query params should correctly slice results."""
    for i in range(5):
        job = await seed_job(_id=ObjectId(), source_job_id=f"gh_test_{i}")
        client.post("/api/saved-jobs", json={"job_id": str(job["_id"])}, headers=auth_headers)

    r = client.get("/api/saved-jobs?skip=1&limit=2", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert body["skip"] == 1
    assert body["limit"] == 2
    assert len(body["jobs"]) == 2


async def test_list_returns_live_job_data(client, mock_async_db, seed_job, auth_headers):
    """A saved job whose parent is still in the jobs collection must return full fields."""
    job = await seed_job(title="Backend Engineer", company="TestCo")
    client.post("/api/saved-jobs", json={"job_id": str(job["_id"])}, headers=auth_headers)
    r = client.get("/api/saved-jobs", headers=auth_headers)
    body = r.json()
    assert len(body["jobs"]) == 1
    entry = body["jobs"][0]
    assert entry["title"] == "Backend Engineer"
    assert entry["company"] == "TestCo"
    assert entry["expired"] is False


async def test_expired_saved_job_id_is_string_not_objectid(client, mock_async_db, seed_job, auth_headers):
    """
    F-08 + N-18 regression guard — when the underlying job has been deleted, the
    returned `id` field must be a JSON string, not a raw ObjectId that leaks type
    through the serializer.
    """
    job = await seed_job()
    job_id = job["_id"]
    client.post("/api/saved-jobs", json={"job_id": str(job_id)}, headers=auth_headers)
    await mock_async_db.jobs.delete_one({"_id": job_id})  # simulate expiry

    r = client.get("/api/saved-jobs", headers=auth_headers)
    body = r.json()
    assert len(body["jobs"]) == 1
    entry = body["jobs"][0]
    assert entry["expired"] is True
    assert isinstance(entry["id"], str)
    assert entry["id"] == str(job_id)


# ─────────────────────────────────────────────────────────────
# Cross-cutting — auth requirement
# ─────────────────────────────────────────────────────────────

def test_saved_jobs_requires_auth(unauth_client):
    """Missing Authorization header should return 401 before hitting any route logic."""
    r = unauth_client.get("/api/saved-jobs")
    assert r.status_code == 401
