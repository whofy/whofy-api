"""
Tests for process_single_job() and process_jobs_batch() in
listings/shared/pipeline.py — the shared enrichment/filter pipeline that
every API-based fetcher hands off to.

Guards:
  - Tech filter rejects non-tech jobs with filtered_reason='tech'
  - Language filter rejects non-English jobs with filtered_reason='lang'
  - Enrichment populates required_skills / work_type / experience_level
  - Explicit provider-supplied work_type/experience_level is preserved
  - raw_description is stripped after processing (IPC memory saving)
  - process_jobs_batch counts filters correctly and handles the empty-input case
  - Small-batch (< 300) path runs synchronously without needing an MP executor
"""

from listings.shared.pipeline import process_single_job, process_jobs_batch


# ─────────────────────────────────────────────────────────────
# process_single_job — filter paths
# ─────────────────────────────────────────────────────────────

def test_process_single_job_rejects_non_tech():
    """A non-tech title should get marked filtered_reason='tech' and NOT be enriched."""
    job = {
        "title": "Registered Nurse",
        "raw_description": "<p>Provide patient care in our hospital ward.</p>",
        "location": "Bengaluru, India",
    }
    result = process_single_job(job)
    assert result["filtered_reason"] == "tech"
    assert "required_skills" not in result


def test_process_single_job_rejects_non_english():
    """A Spanish job description should get marked filtered_reason='lang'."""
    job = {
        "title": "Ingeniero de Software",
        "raw_description": (
            "<p>Buscamos un ingeniero de software con experiencia en desarrollo backend "
            "para unirse a nuestro equipo. Se requiere conocimiento sólido de Python.</p>"
        ),
        "location": "Madrid",
    }
    result = process_single_job(job)
    assert result["filtered_reason"] == "lang"


# ─────────────────────────────────────────────────────────────
# process_single_job — enrichment path
# ─────────────────────────────────────────────────────────────

def test_process_single_job_enriches_accepted_job():
    """An English tech job should get required_skills, work_type, experience_level filled in."""
    job = {
        "title": "Senior Backend Engineer",
        "raw_description": (
            "<p>We are looking for a senior backend engineer with 8+ years of experience. "
            "You'll work with Python, PostgreSQL, and Docker on our platform team. "
            "This is a fully remote position.</p>"
        ),
        "location": "Bengaluru, India",
    }
    result = process_single_job(job)
    assert result["filtered_reason"] is None
    assert "Python" in result["required_skills"]
    assert result["work_type"] == "Remote"
    assert result["experience_level"] == "Senior"


def test_process_single_job_preserves_provider_supplied_work_type():
    """
    If the fetcher already set work_type from source-native data (e.g., Lever's
    workplaceType field), the pipeline must NOT overwrite it with a regex guess.
    """
    job = {
        "title": "Software Engineer",
        "raw_description": "<p>Great role for backend Python developers with cloud experience.</p>",
        "location": "New York",
        "work_type": "Hybrid",  # provider-supplied — must survive
    }
    result = process_single_job(job)
    assert result["work_type"] == "Hybrid"


def test_process_single_job_strips_raw_description():
    """raw_description should be removed from output to save memory in IPC transfer."""
    job = {
        "title": "Backend Engineer",
        "raw_description": "<p>Python, Django, AWS. Great backend developer role for our team.</p>",
        "location": "Remote",
    }
    result = process_single_job(job)
    assert "raw_description" not in result


# ─────────────────────────────────────────────────────────────
# process_jobs_batch — orchestration
# ─────────────────────────────────────────────────────────────

def test_process_jobs_batch_empty_input_returns_empty_counts():
    result = process_jobs_batch([])
    assert result == {"accepted": [], "tech_filtered": 0, "lang_filtered": 0}


def test_process_jobs_batch_counts_filters_correctly():
    """Batch result must correctly split accepted / tech-filtered / lang-filtered."""
    jobs = [
        # accepted
        {"title": "Backend Engineer", "raw_description": "<p>Python and Django. Great role for a backend developer.</p>", "location": "Remote"},
        # tech filtered
        {"title": "Registered Nurse", "raw_description": "<p>Patient care.</p>", "location": "Hospital"},
        # lang filtered
        {"title": "Desarrollador Backend",
         "raw_description": "<p>Buscamos un desarrollador backend con experiencia en Python y bases de datos relacionales.</p>",
         "location": "Madrid"},
        # accepted
        {"title": "Data Scientist", "raw_description": "<p>Python, SQL, machine learning experience needed for our data science team.</p>", "location": "London"},
    ]
    result = process_jobs_batch(jobs)
    assert len(result["accepted"]) == 2
    assert result["tech_filtered"] == 1
    assert result["lang_filtered"] == 1
    # filtered_reason should be stripped from accepted jobs
    for job in result["accepted"]:
        assert "filtered_reason" not in job


def test_process_jobs_batch_small_batch_runs_synchronously():
    """
    Batches of < 300 jobs must run synchronously (no MP executor needed).
    Pickling overhead for small batches beats the parallel speedup.
    """
    jobs = [
        {"title": f"Backend Engineer {i}",
         "raw_description": "<p>Python and Django role for backend developers.</p>",
         "location": "Remote"}
        for i in range(10)
    ]
    # Not passing mp_executor — should still work fine
    result = process_jobs_batch(jobs)
    assert len(result["accepted"]) == 10
