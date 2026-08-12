import re
import time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from listings.shared.pipeline import process_jobs_batch
from listings.shared.storage import save_jobs

MAX_AGE_DAYS = 30
PAGE_SIZE = 20
MAX_JOBS_PER_COMPANY = 1000

COMPANIES = [
    {"name": "Adobe", "domain": "adobe.com",
     "jobs_url": "https://adobe.wd5.myworkdayjobs.com/wday/cxs/adobe/external_experienced/jobs",
     "detail_base": "https://adobe.wd5.myworkdayjobs.com/wday/cxs/adobe/external_experienced",
     "apply_base": "https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced"},
    {"name": "Salesforce", "domain": "salesforce.com",
     "jobs_url": "https://salesforce.wd12.myworkdayjobs.com/wday/cxs/salesforce/External_Career_Site/jobs",
     "detail_base": "https://salesforce.wd12.myworkdayjobs.com/wday/cxs/salesforce/External_Career_Site",
     "apply_base": "https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site"},
    {"name": "NVIDIA", "domain": "nvidia.com",
     "jobs_url": "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs",
     "detail_base": "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite",
     "apply_base": "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite"},
    {"name": "Intel", "domain": "intel.com",
     "jobs_url": "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs",
     "detail_base": "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External",
     "apply_base": "https://intel.wd1.myworkdayjobs.com/en-US/External"},
    {"name": "HP", "domain": "hp.com",
     "jobs_url": "https://hp.wd5.myworkdayjobs.com/wday/cxs/hp/ExternalCareerSite/jobs",
     "detail_base": "https://hp.wd5.myworkdayjobs.com/wday/cxs/hp/ExternalCareerSite",
     "apply_base": "https://hp.wd5.myworkdayjobs.com/en-US/ExternalCareerSite"},
    {"name": "PayPal", "domain": "paypal.com",
     "jobs_url": "https://paypal.wd1.myworkdayjobs.com/wday/cxs/paypal/jobs/jobs",
     "detail_base": "https://paypal.wd1.myworkdayjobs.com/wday/cxs/paypal/jobs",
     "apply_base": "https://paypal.wd1.myworkdayjobs.com/en-US/jobs"},
    {"name": "Broadcom", "domain": "broadcom.com",
     "jobs_url": "https://broadcom.wd1.myworkdayjobs.com/wday/cxs/broadcom/External_Career/jobs",
     "detail_base": "https://broadcom.wd1.myworkdayjobs.com/wday/cxs/broadcom/External_Career",
     "apply_base": "https://broadcom.wd1.myworkdayjobs.com/en-US/External_Career"},
    {"name": "Workday", "domain": "workday.com",
     "jobs_url": "https://workday.wd5.myworkdayjobs.com/wday/cxs/workday/Workday/jobs",
     "detail_base": "https://workday.wd5.myworkdayjobs.com/wday/cxs/workday/Workday",
     "apply_base": "https://workday.wd5.myworkdayjobs.com/en-US/Workday"},
    {"name": "Autodesk", "domain": "autodesk.com",
     "jobs_url": "https://autodesk.wd1.myworkdayjobs.com/wday/cxs/autodesk/Ext/jobs",
     "detail_base": "https://autodesk.wd1.myworkdayjobs.com/wday/cxs/autodesk/Ext",
     "apply_base": "https://autodesk.wd1.myworkdayjobs.com/en-US/Ext"},
    {"name": "Target", "domain": "target.com",
     "jobs_url": "https://target.wd5.myworkdayjobs.com/wday/cxs/target/targetcareers/jobs",
     "detail_base": "https://target.wd5.myworkdayjobs.com/wday/cxs/target/targetcareers",
     "apply_base": "https://target.wd5.myworkdayjobs.com/en-US/targetcareers"},
    {"name": "Zoom", "domain": "zoom.us",
     "jobs_url": "https://zoom.wd5.myworkdayjobs.com/wday/cxs/zoom/Zoom/jobs",
     "detail_base": "https://zoom.wd5.myworkdayjobs.com/wday/cxs/zoom/Zoom",
     "apply_base": "https://zoom.wd5.myworkdayjobs.com/en-US/Zoom"},
    {"name": "Samsung", "domain": "samsung.com",
     "jobs_url": "https://sec.wd3.myworkdayjobs.com/wday/cxs/sec/Samsung_Careers/jobs",
     "detail_base": "https://sec.wd3.myworkdayjobs.com/wday/cxs/sec/Samsung_Careers",
     "apply_base": "https://sec.wd3.myworkdayjobs.com/en-US/Samsung_Careers"},
    {"name": "T-Mobile", "domain": "t-mobile.com",
     "jobs_url": "https://tmobile.wd1.myworkdayjobs.com/wday/cxs/tmobile/External/jobs",
     "detail_base": "https://tmobile.wd1.myworkdayjobs.com/wday/cxs/tmobile/External",
     "apply_base": "https://tmobile.wd1.myworkdayjobs.com/en-US/External"},
    {"name": "Mastercard", "domain": "mastercard.com",
     "jobs_url": "https://mastercard.wd1.myworkdayjobs.com/wday/cxs/mastercard/CorporateCareers/jobs",
     "detail_base": "https://mastercard.wd1.myworkdayjobs.com/wday/cxs/mastercard/CorporateCareers",
     "apply_base": "https://mastercard.wd1.myworkdayjobs.com/en-US/CorporateCareers"},
    {"name": "CrowdStrike", "domain": "crowdstrike.com",
     "jobs_url": "https://crowdstrike.wd5.myworkdayjobs.com/wday/cxs/crowdstrike/crowdstrikecareers/jobs",
     "detail_base": "https://crowdstrike.wd5.myworkdayjobs.com/wday/cxs/crowdstrike/crowdstrikecareers",
     "apply_base": "https://crowdstrike.wd5.myworkdayjobs.com/en-US/crowdstrikecareers"},
    {"name": "Micron", "domain": "micron.com",
     "jobs_url": "https://micron.wd1.myworkdayjobs.com/wday/cxs/micron/External/jobs",
     "detail_base": "https://micron.wd1.myworkdayjobs.com/wday/cxs/micron/External",
     "apply_base": "https://micron.wd1.myworkdayjobs.com/en-US/External"},
    {"name": "Applied Materials", "domain": "appliedmaterials.com",
     "jobs_url": "https://amat.wd1.myworkdayjobs.com/wday/cxs/amat/External/jobs",
     "detail_base": "https://amat.wd1.myworkdayjobs.com/wday/cxs/amat/External",
     "apply_base": "https://amat.wd1.myworkdayjobs.com/en-US/External"},
    {"name": "Cadence", "domain": "cadence.com",
     "jobs_url": "https://cadence.wd1.myworkdayjobs.com/wday/cxs/cadence/External_Careers/jobs",
     "detail_base": "https://cadence.wd1.myworkdayjobs.com/wday/cxs/cadence/External_Careers",
     "apply_base": "https://cadence.wd1.myworkdayjobs.com/en-US/External_Careers"},
    {"name": "Marvell", "domain": "marvell.com",
     "jobs_url": "https://marvell.wd1.myworkdayjobs.com/wday/cxs/marvell/MarvellCareers/jobs",
     "detail_base": "https://marvell.wd1.myworkdayjobs.com/wday/cxs/marvell/MarvellCareers",
     "apply_base": "https://marvell.wd1.myworkdayjobs.com/en-US/MarvellCareers"},
    {"name": "Motorola Solutions", "domain": "motorolasolutions.com",
     "jobs_url": "https://motorolasolutions.wd5.myworkdayjobs.com/wday/cxs/motorolasolutions/Careers/jobs",
     "detail_base": "https://motorolasolutions.wd5.myworkdayjobs.com/wday/cxs/motorolasolutions/Careers",
     "apply_base": "https://motorolasolutions.wd5.myworkdayjobs.com/en-US/Careers"},
    {"name": "KLA", "domain": "kla.com",
     "jobs_url": "https://kla.wd1.myworkdayjobs.com/wday/cxs/kla/Search/jobs",
     "detail_base": "https://kla.wd1.myworkdayjobs.com/wday/cxs/kla/Search",
     "apply_base": "https://kla.wd1.myworkdayjobs.com/en-US/Search"},
    {"name": "Analog Devices", "domain": "analog.com",
     "jobs_url": "https://analogdevices.wd1.myworkdayjobs.com/wday/cxs/analogdevices/External/jobs",
     "detail_base": "https://analogdevices.wd1.myworkdayjobs.com/wday/cxs/analogdevices/External",
     "apply_base": "https://analogdevices.wd1.myworkdayjobs.com/en-US/External"},
    {"name": "NXP", "domain": "nxp.com",
     "jobs_url": "https://nxp.wd3.myworkdayjobs.com/wday/cxs/nxp/careers/jobs",
     "detail_base": "https://nxp.wd3.myworkdayjobs.com/wday/cxs/nxp/careers",
     "apply_base": "https://nxp.wd3.myworkdayjobs.com/en-US/careers"},
    {"name": "Trimble", "domain": "trimble.com",
     "jobs_url": "https://trimble.wd1.myworkdayjobs.com/wday/cxs/trimble/TrimbleCareers/jobs",
     "detail_base": "https://trimble.wd1.myworkdayjobs.com/wday/cxs/trimble/TrimbleCareers",
     "apply_base": "https://trimble.wd1.myworkdayjobs.com/en-US/TrimbleCareers"},
    {"name": "Rockwell Automation", "domain": "rockwellautomation.com",
     "jobs_url": "https://rockwellautomation.wd1.myworkdayjobs.com/wday/cxs/rockwellautomation/External_Rockwell_Automation/jobs",
     "detail_base": "https://rockwellautomation.wd1.myworkdayjobs.com/wday/cxs/rockwellautomation/External_Rockwell_Automation",
     "apply_base": "https://rockwellautomation.wd1.myworkdayjobs.com/en-US/External_Rockwell_Automation"},
    {"name": "Medtronic", "domain": "medtronic.com",
     "jobs_url": "https://medtronic.wd1.myworkdayjobs.com/wday/cxs/medtronic/MedtronicCareers/jobs",
     "detail_base": "https://medtronic.wd1.myworkdayjobs.com/wday/cxs/medtronic/MedtronicCareers",
     "apply_base": "https://medtronic.wd1.myworkdayjobs.com/en-US/MedtronicCareers"},
    {"name": "GlobalFoundries", "domain": "globalfoundries.com",
     "jobs_url": "https://globalfoundries.wd1.myworkdayjobs.com/wday/cxs/globalfoundries/External/jobs",
     "detail_base": "https://globalfoundries.wd1.myworkdayjobs.com/wday/cxs/globalfoundries/External",
     "apply_base": "https://globalfoundries.wd1.myworkdayjobs.com/en-US/External"},
]

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Whofy Job Aggregator (contact: whofyteam@gmail.com)",
}


def _parse_posted_age(posted_on: str) -> int | None:
    if not posted_on:
        return None
    m = re.search(r"(\d+)\s*Day", posted_on, re.IGNORECASE)
    if m:
        return int(m.group(1))
    if "today" in posted_on.lower() or "just posted" in posted_on.lower():
        return 0
    if "yesterday" in posted_on.lower():
        return 1
    if "30+" in posted_on:
        return 31
    return None


def _posted_at_from_age(days_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.isoformat()


def fetch_workday_jobs(company: dict) -> list[dict]:
    jobs_url = company["jobs_url"]
    detail_base = company["detail_base"]
    apply_base = company["apply_base"]

    all_listings = []
    offset = 0

    while offset < MAX_JOBS_PER_COMPANY:
        try:
            resp = requests.post(
                jobs_url,
                json={"limit": PAGE_SIZE, "offset": offset, "searchText": ""},
                headers=HEADERS,
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"  HTTP {resp.status_code} at offset {offset}, stopping")
                break
            data = resp.json()
        except Exception as e:
            print(f"  Error fetching {company['name']} at offset {offset}: {e}")
            break

        postings = data.get("jobPostings", [])
        if not postings:
            break

        total = data.get("total", 0)

        for job in postings:
            posted_on = job.get("postedOn", "")
            days_ago = _parse_posted_age(posted_on)

            if days_ago is not None and days_ago > MAX_AGE_DAYS:
                continue

            title = job.get("title", "")
            location = job.get("locationsText", "Not specified")
            external_path = job.get("externalPath", "")
            apply_url = f"{apply_base}{external_path}" if external_path else ""
            posted_at = _posted_at_from_age(days_ago) if days_ago is not None else ""

            slug = external_path.rstrip("/").rsplit("/", 1)[-1] if external_path else ""
            source_id = f"wd_{company['name'].lower().replace(' ', '')}_{slug}"

            all_listings.append({
                "title": title,
                "location": location,
                "apply_url": apply_url,
                "posted_at": posted_at,
                "description": None,
                "data_quality_flags": ["missing_description"],
                "external_path": external_path,
                "source_id": source_id,
            })

        offset += PAGE_SIZE
        if offset >= total:
            break
        time.sleep(0.5)

    if not all_listings:
        return []

    print(f"  -> {len(all_listings)} listings (within {MAX_AGE_DAYS} days)")

    # Return raw jobs — process_jobs_batch handles enrichment via the shared pipeline.
    # Workday's search API doesn't return descriptions; detection_text = title + location
    # preserves the current behavior of using location as a signal for skill/work-type detection.
    normalized = []
    for listing in all_listings:
        title = listing["title"]
        location = listing["location"]
        normalized.append({
            "source": "workday",
            "source_job_id": listing["source_id"],
            "title": title,
            "company": company["name"],
            "company_domain": company.get("domain", ""),
            "location": location,
            "raw_description": "",  # Workday API omits descriptions
            "detection_text": f"{title} {location}",
            "apply_url": listing["apply_url"],
            "posted_at": listing["posted_at"],
        })

    return normalized


def main(mp_executor=None):
    all_jobs = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_workday_jobs, company): company for company in COMPANIES}
        for future in as_completed(futures):
            company = futures[future]
            print(f"Fetching jobs for {company['name']}...")
            try:
                jobs = future.result()
                all_jobs.extend(jobs)
            except Exception as e:
                print(f"  ERROR for {company['name']}: {e}")

    print(f"\nTotal jobs fetched: {len(all_jobs)}")

    print("Running process_jobs_batch (enrichment + filtering)...")
    batch_result = process_jobs_batch(all_jobs, mp_executor=mp_executor)
    accepted_jobs = batch_result["accepted"]
    tech_filtered = batch_result["tech_filtered"]
    lang_filtered = batch_result["lang_filtered"]
    print(f"After MP enrichment/filter: {len(accepted_jobs)} accepted")
    print(f"Filtered (Tech): {tech_filtered}")
    print(f"Filtered (Lang): {lang_filtered}")

    if accepted_jobs:
        result = save_jobs(accepted_jobs, source="workday")
        result["tech_filtered"] = tech_filtered
        result["non_english_skipped"] = lang_filtered
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
