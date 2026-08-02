import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from listings.shared.enrich import bake_required_skills, detect_experience, detect_work_type, extract_required_skills
from listings.shared.normalize import full_text, strip_html
from listings.shared.storage import save_jobs
from listings.shared.tech_filter import filter_tech_jobs

ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{company}"

COMPANIES = [
    {"name": "OpenAI", "slug": "openai", "domain": "openai.com"},
    {"name": "Snowflake", "slug": "snowflake", "domain": "snowflake.com"},
    {"name": "Harvey AI", "slug": "harvey", "domain": "harvey.ai"},
    {"name": "ElevenLabs", "slug": "elevenlabs", "domain": "elevenlabs.io"},
    {"name": "Cohere", "slug": "cohere", "domain": "cohere.com"},
    {"name": "Notion", "slug": "notion", "domain": "notion.so"},
    {"name": "Cursor", "slug": "cursor", "domain": "cursor.com"},
    {"name": "Ramp", "slug": "ramp", "domain": "ramp.com"},
    {"name": "Plaid", "slug": "plaid", "domain": "plaid.com"},
    {"name": "Vanta", "slug": "vanta", "domain": "vanta.com"},
    {"name": "Replit", "slug": "replit", "domain": "replit.com"},
    {"name": "Perplexity", "slug": "perplexity", "domain": "perplexity.ai"},
    {"name": "LangChain", "slug": "langchain", "domain": "langchain.com"},
    {"name": "Deepgram", "slug": "deepgram", "domain": "deepgram.com"},
    {"name": "Baseten", "slug": "baseten", "domain": "baseten.co"},
    {"name": "ClickUp", "slug": "clickup", "domain": "clickup.com"},
    {"name": "Temporal", "slug": "temporal", "domain": "temporal.io"},
    {"name": "Supabase", "slug": "supabase", "domain": "supabase.com"},
    {"name": "Sardine", "slug": "sardine", "domain": "sardine.ai"},
    {"name": "Confluent", "slug": "confluent", "domain": "confluent.io"},
    {"name": "Modal", "slug": "modal", "domain": "modal.com"},
    {"name": "Render", "slug": "render", "domain": "render.com"},
    {"name": "Linear", "slug": "linear", "domain": "linear.app"},
    {"name": "WorkOS", "slug": "workos", "domain": "workos.com"},
    {"name": "Anyscale", "slug": "anyscale", "domain": "anyscale.com"},
    {"name": "Midjourney", "slug": "midjourney", "domain": "midjourney.com"},
    {"name": "Character.AI", "slug": "character", "domain": "character.ai"},
    {"name": "Airbyte", "slug": "airbyte", "domain": "airbyte.com"},
    {"name": "PostHog", "slug": "posthog", "domain": "posthog.com"},
    {"name": "Resend", "slug": "resend", "domain": "resend.com"},
    {"name": "Railway", "slug": "railway", "domain": "railway.app"},
    {"name": "Neon", "slug": "neon", "domain": "neon.tech"},
    {"name": "Monte Carlo", "slug": "montecarlodata", "domain": "montecarlodata.com"},
    {"name": "Atlan", "slug": "atlan", "domain": "atlan.com"},
    {"name": "Prefect", "slug": "prefect", "domain": "prefect.io"},
    {"name": "Pinecone", "slug": "pinecone", "domain": "pinecone.io"},
    {"name": "Stytch", "slug": "stytch", "domain": "stytch.com"},
    {"name": "Weaviate", "slug": "weaviate", "domain": "weaviate.io"},
    {"name": "Runway", "slug": "runway", "domain": "runwayml.com"},
    {"name": "Doppler", "slug": "doppler", "domain": "doppler.com"},
    {"name": "Hightouch", "slug": "hightouch", "domain": "hightouch.com"},
    {"name": "Crusoe", "slug": "crusoe", "domain": "crusoe.ai"},
    {"name": "Zip", "slug": "zip", "domain": "ziphq.com"},
    {"name": "Hinge Health", "slug": "hinge-health", "domain": "hingehealth.com"},
    {"name": "1Password", "slug": "1password", "domain": "1password.com"},
    {"name": "Benchling", "slug": "benchling", "domain": "benchling.com"},
    {"name": "Sentry", "slug": "sentry", "domain": "sentry.io"},
    {"name": "Amplitude", "slug": "amplitude", "domain": "amplitude.com"},
    {"name": "Span", "slug": "span", "domain": "span.io"},
    {"name": "Strava", "slug": "strava", "domain": "strava.com"},
    {"name": "LiveKit", "slug": "livekit", "domain": "livekit.io"},
    {"name": "Persona", "slug": "persona", "domain": "withpersona.com"},
    {"name": "Column", "slug": "column", "domain": "column.com"},
    {"name": "Semgrep", "slug": "semgrep", "domain": "semgrep.dev"},
    {"name": "Envoy", "slug": "envoy", "domain": "envoy.com"},
    {"name": "Sequoia", "slug": "sequoia", "domain": "sequoiacap.com"},
    {"name": "Zapier", "slug": "zapier", "domain": "zapier.com"},
    {"name": "Propel", "slug": "propel", "domain": "propelauth.com"},
    {"name": "Materialize", "slug": "materialize", "domain": "materialize.com"},
    {"name": "Oso", "slug": "oso", "domain": "osohq.com"},
    {"name": "Axiom", "slug": "axiom", "domain": "axiom.co"},
]

HEADERS = {
    "User-Agent": "Whofy Job Aggregator (contact: whofyteam@gmail.com)"
}


def fetch_ashby_jobs(company: dict) -> list[dict]:
    url = ASHBY_API.format(company=company["slug"])
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Error fetching {company['name']}: {e}")
        return []

    data = resp.json()
    raw_jobs = data.get("jobs", [])
    if not raw_jobs:
        return []
    print(f"  -> {len(raw_jobs)} jobs found")

    normalized = []
    for job in raw_jobs:
        title = job.get("title", "")
        location = job.get("location", "Not specified")
        if isinstance(location, dict):
            location = location.get("name", "Not specified")

        raw_description = job.get("descriptionHtml", "") or job.get("description", "")
        
        job_url = job.get("jobUrl", "")
        if not job_url:
            job_url = f"https://jobs.ashbyhq.com/{company['slug']}/{job.get('id', '')}"
            
        normalized.append({
            "source": "ashby",
            "source_job_id": f"ash_{job.get('id', '')}",
            "title": title,
            "company": company["name"],
            "company_domain": company.get("domain", ""),
            "location": location,
            "raw_description": raw_description,
            "apply_url": job_url,
            "posted_at": job.get("publishedAt", ""),
        })

    return normalized


from listings.shared.pipeline import process_jobs_batch

def main(mp_executor=None):
    all_jobs = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_ashby_jobs, company): company for company in COMPANIES}
        for future in as_completed(futures):
            company = futures[future]
            print(f"Fetching jobs for {company['name']}...")
            try:
                jobs = future.result()
                all_jobs.extend(jobs)
            except Exception as e:
                print(f"Error processing {company['name']}: {e}")

    import time
    t_start = time.time()
    
    print(f"\nTotal jobs fetched: {len(all_jobs)}")

    print("Running process_jobs_batch (enrichment + filtering)...")
    batch_result = process_jobs_batch(all_jobs, mp_executor=mp_executor)
    accepted_jobs = batch_result["accepted"]
    tech_filtered = batch_result["tech_filtered"]
    lang_filtered = batch_result["lang_filtered"]
    
    t_filter = time.time()
    print(f"After MP enrichment/filter: {len(accepted_jobs)} accepted")
    print(f"Filtered (Tech): {tech_filtered}")
    print(f"Filtered (Lang): {lang_filtered}")

    if accepted_jobs:
        result = save_jobs(accepted_jobs, source="ashby")
        result["tech_filtered"] = tech_filtered
        result["non_english_skipped"] = lang_filtered
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
