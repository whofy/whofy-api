import os
from concurrent.futures import ProcessPoolExecutor
from langdetect import detect
from listings.shared.enrich import extract_required_skills, detect_work_type, detect_experience, bake_required_skills
from listings.shared.normalize import full_text, strip_html
from listings.shared.tech_filter import is_tech_job

def _is_non_english(title: str, desc: str) -> bool:
    text = f"{title} {desc}".strip()
    if not text:
        return False
    try:
        lang = detect(text)
        return lang != "en"
    except Exception:
        return False

def process_single_job(job: dict) -> dict | None:
    """
    Enriches a raw job dictionary. 
    Returns None if it fails tech filter or non-English filter.
    """
    title = job.get("title", "")
    raw_desc = job.get("raw_description", "")
    location = job.get("location", "")
    
    desc = job.get("description")
    if desc is None:
        desc = strip_html(raw_desc)
        
    detection_text = job.get("detection_text")
    if detection_text is None:
        detection_text = full_text(raw_desc)
    
    # 1. Tech Filter
    if not is_tech_job(title, desc):
        job["filtered_reason"] = "tech"
        return job

    # 2. Non-English Filter
    if _is_non_english(title, desc[:500]):
        job["filtered_reason"] = "lang"
        return job
        
    req_skills = extract_required_skills(title, detection_text)
    
    # If the job explicitly provided work_type or experience_level, keep it, otherwise detect
    work_type = job.get("work_type") or detect_work_type(title, location, detection_text)
    exp = job.get("experience_level") or detect_experience(title, detection_text)
    
    job["description"] = bake_required_skills(desc, req_skills)
    job["required_skills"] = req_skills
    job["work_type"] = work_type
    job["experience_level"] = exp
    job["filtered_reason"] = None
    
    # Remove raw HTML to save memory in IPC transfer
    if "raw_description" in job:
        del job["raw_description"]
        
    return job

def process_jobs_batch(jobs: list[dict], mp_executor: ProcessPoolExecutor = None) -> dict:
    """
    Takes a list of raw jobs, processes them using ProcessPoolExecutor if large enough,
    and returns a dict of separated accepted/filtered jobs.
    """
    if not jobs:
        return {"accepted": [], "tech_filtered": 0, "lang_filtered": 0}
        
    # If the batch is small, processing synchronously is faster than pickling overhead
    if len(jobs) < 300:
        results = [process_single_job(j) for j in jobs]
    else:
        # Use a sensible max_workers for GitHub Actions (at least 2, max CPU count)
        workers = min(16, max(2, os.cpu_count() or 2))
        # Batch size for ProcessPoolExecutor to minimize IPC
        chunksize = max(1, len(jobs) // (workers * 4))
        
        if mp_executor:
            results = list(mp_executor.map(process_single_job, jobs, chunksize=chunksize))
        else:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                results = list(executor.map(process_single_job, jobs, chunksize=chunksize))
            
    accepted = []
    tech_filtered = 0
    lang_filtered = 0
    
    for res in results:
        reason = res.get("filtered_reason")
        if reason == "tech":
            tech_filtered += 1
        elif reason == "lang":
            lang_filtered += 1
        else:
            if "filtered_reason" in res:
                del res["filtered_reason"]
            accepted.append(res)
            
    return {
        "accepted": accepted,
        "tech_filtered": tech_filtered,
        "lang_filtered": lang_filtered
    }
