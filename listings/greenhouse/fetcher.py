import requests
from listings.shared.enrich import bake_required_skills, detect_experience, detect_work_type, extract_required_skills
from listings.shared.normalize import full_text, strip_html
from listings.shared.storage import save_jobs
from listings.shared.tech_filter import filter_tech_jobs

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"

COMPANIES = [
    {"name": "Airbnb", "board_token": "airbnb", "domain": "airbnb.com"},
    {"name": "Airtable", "board_token": "airtable", "domain": "airtable.com"},
    {"name": "Algolia", "board_token": "algolia", "domain": "algolia.com"},
    {"name": "Amplitude", "board_token": "amplitude", "domain": "amplitude.com"},
    {"name": "Anthropic", "board_token": "anthropic", "domain": "anthropic.com"},
    {"name": "Apollo", "board_token": "apolloio", "domain": "apollo.io"},
    {"name": "AppLovin", "board_token": "applovin", "domain": "applovin.com"},
    {"name": "AppsFlyer", "board_token": "appsflyer", "domain": "appsflyer.com"},
    {"name": "Asana", "board_token": "asana", "domain": "asana.com"},
    {"name": "Attentive", "board_token": "attentive", "domain": "attentivemobile.com"},
    {"name": "Axon", "board_token": "axon", "domain": "axon.com"},
    {"name": "Adyen", "board_token": "adyen", "domain": "adyen.com"},
    {"name": "Akuna Capital", "board_token": "akunacapital", "domain": "akunacapital.com"},
    {"name": "Bill.com", "board_token": "billcom", "domain": "bill.com"},
    {"name": "Bloomerang", "board_token": "bloomerang", "domain": "bloomerang.co"},
    {"name": "Branch", "board_token": "branch", "domain": "branch.io"},
    {"name": "Braze", "board_token": "braze", "domain": "braze.com"},
    {"name": "Brex", "board_token": "brex", "domain": "brex.com"},
    {"name": "Calendly", "board_token": "calendly", "domain": "calendly.com"},
    {"name": "Carta", "board_token": "carta", "domain": "carta.com"},
    {"name": "Celonis", "board_token": "celonis", "domain": "celonis.com"},
    {"name": "Checkr", "board_token": "checkr", "domain": "checkr.com"},
    {"name": "Chime", "board_token": "chime", "domain": "chime.com"},
    {"name": "CircleCI", "board_token": "circleci", "domain": "circleci.com"},
    {"name": "Cloudflare", "board_token": "cloudflare", "domain": "cloudflare.com"},
    {"name": "Cockroach Labs", "board_token": "cockroachlabs", "domain": "cockroachlabs.com"},
    {"name": "Coinbase", "board_token": "coinbase", "domain": "coinbase.com"},
    {"name": "CoreWeave", "board_token": "coreweave", "domain": "coreweave.com"},
    {"name": "Coupang", "board_token": "coupang", "domain": "coupang.com"},
    {"name": "Cribl", "board_token": "cribl", "domain": "cribl.io"},
    {"name": "Culture Amp", "board_token": "cultureamp", "domain": "cultureamp.com"},
    {"name": "Databricks", "board_token": "databricks", "domain": "databricks.com"},
    {"name": "Datadog", "board_token": "datadog", "domain": "datadoghq.com"},
    {"name": "Discord", "board_token": "discord", "domain": "discord.com"},
    {"name": "DoorDash", "board_token": "doordashusa", "domain": "doordash.com"},
    {"name": "Dropbox", "board_token": "dropbox", "domain": "dropbox.com"},
    {"name": "Duolingo", "board_token": "duolingo", "domain": "duolingo.com"},
    {"name": "Earnin", "board_token": "earnin", "domain": "earnin.com"},
    {"name": "Elastic", "board_token": "elastic", "domain": "elastic.co"},
    {"name": "Epic Games", "board_token": "epicgames", "domain": "epicgames.com"},
    {"name": "Faire", "board_token": "faire", "domain": "faire.com"},
    {"name": "Fastly", "board_token": "fastly", "domain": "fastly.com"},
    {"name": "Figma", "board_token": "figma", "domain": "figma.com"},
    {"name": "Fireblocks", "board_token": "fireblocks", "domain": "fireblocks.com"},
    {"name": "Fivetran", "board_token": "fivetran", "domain": "fivetran.com"},
    {"name": "Flatiron Health", "board_token": "flatironhealth", "domain": "flatironhealth.com"},
    {"name": "Flexport", "board_token": "flexport", "domain": "flexport.com"},
    {"name": "Forter", "board_token": "forter", "domain": "forter.com"},
    {"name": "Ginkgo Bioworks", "board_token": "ginkgobioworks", "domain": "ginkgobioworks.com"},
    {"name": "GitLab", "board_token": "gitlab", "domain": "gitlab.com"},
    {"name": "GoCardless", "board_token": "gocardless", "domain": "gocardless.com"},
    {"name": "Grafana Labs", "board_token": "grafanalabs", "domain": "grafana.com"},
    {"name": "Gusto", "board_token": "gusto", "domain": "gusto.com"},
    {"name": "HealthJoy", "board_token": "healthjoy", "domain": "healthjoy.com"},
    {"name": "Instacart", "board_token": "instacart", "domain": "instacart.com"},
    {"name": "Intercom", "board_token": "intercom", "domain": "intercom.com"},
    {"name": "IonQ", "board_token": "ionq", "domain": "ionq.com"},
    {"name": "Iterable", "board_token": "iterable", "domain": "iterable.com"},
    {"name": "JFrog", "board_token": "jfrog", "domain": "jfrog.com"},
    {"name": "Justworks", "board_token": "justworks", "domain": "justworks.com"},
    {"name": "Karat", "board_token": "karat", "domain": "karat.com"},
    {"name": "Klaviyo", "board_token": "klaviyo", "domain": "klaviyo.com"},
    {"name": "Lattice", "board_token": "lattice", "domain": "lattice.com"},
    {"name": "LaunchDarkly", "board_token": "launchdarkly", "domain": "launchdarkly.com"},
    {"name": "Lyft", "board_token": "lyft", "domain": "lyft.com"},
    {"name": "Marqeta", "board_token": "marqeta", "domain": "marqeta.com"},
    {"name": "MasterClass", "board_token": "masterclass", "domain": "masterclass.com"},
    {"name": "Medium", "board_token": "medium", "domain": "medium.com"},
    {"name": "Mercury", "board_token": "mercury", "domain": "mercury.com"},
    {"name": "Mixpanel", "board_token": "mixpanel", "domain": "mixpanel.com"},
    {"name": "MongoDB", "board_token": "mongodb", "domain": "mongodb.com"},
    {"name": "Nearform", "board_token": "nearform", "domain": "nearform.com"},
    {"name": "Netlify", "board_token": "netlify", "domain": "netlify.com"},
    {"name": "Nextdoor", "board_token": "nextdoor", "domain": "nextdoor.com"},
    {"name": "Nuro", "board_token": "nuro", "domain": "nuro.ai"},
    {"name": "Okta", "board_token": "okta", "domain": "okta.com"},
    {"name": "OneTrust", "board_token": "onetrust", "domain": "onetrust.com"},
    {"name": "Orca Security", "board_token": "orcasecurity", "domain": "orca.security"},
    {"name": "PagerDuty", "board_token": "pagerduty", "domain": "pagerduty.com"},
    {"name": "PandaDoc", "board_token": "pandadoc", "domain": "pandadoc.com"},
    {"name": "Pinterest", "board_token": "pinterest", "domain": "pinterest.com"},
    {"name": "PlanetScale", "board_token": "planetscale", "domain": "planetscale.com"},
    {"name": "Plume", "board_token": "plume", "domain": "plume.com"},
    {"name": "Postman", "board_token": "postman", "domain": "postman.com"},
    {"name": "Postscript", "board_token": "postscript", "domain": "postscript.io"},
    {"name": "Qualtrics", "board_token": "qualtrics", "domain": "qualtrics.com"},
    {"name": "Razorpay", "board_token": "razorpaysoftwareprivatelimited", "domain": "razorpay.com"},
    {"name": "Recorded Future", "board_token": "recordedfuture", "domain": "recordedfuture.com"},
    {"name": "Reddit", "board_token": "reddit", "domain": "reddit.com"},
    {"name": "Relativity", "board_token": "relativity", "domain": "relativity.com"},
    {"name": "Remote", "board_token": "remotecom", "domain": "remote.com"},
    {"name": "Riot Games", "board_token": "riotgames", "domain": "riotgames.com"},
    {"name": "Ripple", "board_token": "ripple", "domain": "ripple.com"},
    {"name": "Robinhood", "board_token": "robinhood", "domain": "robinhood.com"},
    {"name": "Roblox", "board_token": "roblox", "domain": "roblox.com"},
    {"name": "Roku", "board_token": "roku", "domain": "roku.com"},
    {"name": "Rubrik", "board_token": "rubrik", "domain": "rubrik.com"},
    {"name": "Samsara", "board_token": "samsara", "domain": "samsara.com"},
    {"name": "Scale AI", "board_token": "scaleai", "domain": "scale.com"},
    {"name": "Sigma Computing", "board_token": "sigmacomputing", "domain": "sigmacomputing.com"},
    {"name": "SingleStore", "board_token": "singlestore", "domain": "singlestore.com"},
    {"name": "Snorkel AI", "board_token": "snorkelai", "domain": "snorkel.ai"},
    {"name": "SoFi", "board_token": "sofi", "domain": "sofi.com"},
    {"name": "SpaceX", "board_token": "spacex", "domain": "spacex.com"},
    {"name": "Squarespace", "board_token": "squarespace", "domain": "squarespace.com"},
    {"name": "Starburst", "board_token": "starburst", "domain": "starburst.io"},
    {"name": "StockX", "board_token": "stockx", "domain": "stockx.com"},
    {"name": "Stripe", "board_token": "stripe", "domain": "stripe.com"},
    {"name": "Sumo Logic", "board_token": "sumologic", "domain": "sumologic.com"},
    {"name": "Tailscale", "board_token": "tailscale", "domain": "tailscale.com"},
    {"name": "TaskRabbit", "board_token": "taskrabbit", "domain": "taskrabbit.com"},
    {"name": "The Trade Desk", "board_token": "thetradedesk", "domain": "thetradedesk.com"},
    {"name": "Toast", "board_token": "toast", "domain": "toasttab.com"},
    {"name": "TripActions", "board_token": "tripactions", "domain": "tripactions.com"},
    {"name": "Trustpilot", "board_token": "trustpilot", "domain": "trustpilot.com"},
    {"name": "Twilio", "board_token": "twilio", "domain": "twilio.com"},
    {"name": "Twitch", "board_token": "twitch", "domain": "twitch.tv"},
    {"name": "Udemy", "board_token": "udemy", "domain": "udemy.com"},
    {"name": "Upstart", "board_token": "upstart", "domain": "upstart.com"},
    {"name": "Upwork", "board_token": "upwork", "domain": "upwork.com"},
    {"name": "Vectra AI", "board_token": "vectranetworks", "domain": "vectra.ai"},
    {"name": "Vercel", "board_token": "vercel", "domain": "vercel.com"},
    {"name": "Verkada", "board_token": "verkada", "domain": "verkada.com"},
    {"name": "Webflow", "board_token": "webflow", "domain": "webflow.com"},
    {"name": "Workato", "board_token": "workato", "domain": "workato.com"},
    {"name": "Yext", "board_token": "yext", "domain": "yext.com"},
    {"name": "ZoomInfo", "board_token": "zoominfo", "domain": "zoominfo.com"},
    {"name": "Zscaler", "board_token": "zscaler", "domain": "zscaler.com"},
    {"name": "Zuora", "board_token": "zuora", "domain": "zuora.com"},
    {"name": "Abnormal Security", "board_token": "abnormalsecurity", "domain": "abnormalsecurity.com"},
    {"name": "Airship", "board_token": "airship", "domain": "airship.com"},
    {"name": "Amperity", "board_token": "amperity", "domain": "amperity.com"},
    {"name": "Anaplan", "board_token": "anaplan", "domain": "anaplan.com"},
    {"name": "AssemblyAI", "board_token": "assemblyai", "domain": "assemblyai.com"},
    {"name": "Axonius", "board_token": "axonius", "domain": "axonius.com"},
    {"name": "Bloomreach", "board_token": "bloomreach", "domain": "bloomreach.com"},
    {"name": "BlueConic", "board_token": "blueconic", "domain": "blueconic.com"},
    {"name": "Buildkite", "board_token": "buildkite", "domain": "buildkite.com"},
    {"name": "ClickHouse", "board_token": "clickhouse", "domain": "clickhouse.com"},
    {"name": "Collibra", "board_token": "collibra", "domain": "collibra.com"},
    {"name": "Coursera", "board_token": "coursera", "domain": "coursera.com"},
    {"name": "Dataiku", "board_token": "dataiku", "domain": "dataiku.com"},
    {"name": "Datarails", "board_token": "datarails", "domain": "datarails.com"},
    {"name": "Descript", "board_token": "descript", "domain": "descript.com"},
    {"name": "Five9", "board_token": "five9", "domain": "five9.com"},
    {"name": "Globalization Partners", "board_token": "globalizationpartners", "domain": "globalizationpartners.com"},
    {"name": "Hightouch", "board_token": "hightouch", "domain": "hightouch.com"},
    {"name": "Huntress", "board_token": "huntress", "domain": "huntress.com"},
    {"name": "Imply", "board_token": "imply", "domain": "imply.com"},
    {"name": "Insider", "board_token": "insider", "domain": "insider.com"},
    {"name": "Invisible", "board_token": "invisible", "domain": "invisible.com"},
    {"name": "Labelbox", "board_token": "labelbox", "domain": "labelbox.com"},
    {"name": "Lucid Motors", "board_token": "lucidmotors", "domain": "lucidmotors.com"},
    {"name": "Neo4j", "board_token": "neo4j", "domain": "neo4j.com"},
    {"name": "New Relic", "board_token": "newrelic", "domain": "newrelic.com"},
    {"name": "Observe.AI", "board_token": "observeai", "domain": "observeai.com"},
    {"name": "Otter.ai", "board_token": "otterai", "domain": "otterai.com"},
    {"name": "Pendo", "board_token": "pendo", "domain": "pendo.com"},
    {"name": "Planet Labs", "board_token": "planetlabs", "domain": "planetlabs.com"},
    {"name": "Rocket Lab", "board_token": "rocketlab", "domain": "rocketlab.com"},
    {"name": "Sisense", "board_token": "sisense", "domain": "sisense.com"},
    {"name": "Stability AI", "board_token": "stabilityai", "domain": "stabilityai.com"},
    {"name": "Together AI", "board_token": "togetherai", "domain": "togetherai.com"},
    {"name": "Turing", "board_token": "turing", "domain": "turing.com"},
    {"name": "Via", "board_token": "via", "domain": "via.com"},
    {"name": "Waymo", "board_token": "waymo", "domain": "waymo.com"},
    {"name": "Anduril", "board_token": "andurilindustries", "domain": "anduril.com"},
    {"name": "Block", "board_token": "block", "domain": "block.xyz"},
    {"name": "Tanium", "board_token": "tanium", "domain": "tanium.com"},
]

HEADERS = {
    "User-Agent": "Whofy Job Aggregator (contact: whofyteam@gmail.com)"
}


def fetch_greenhouse_jobs(company: dict) -> list[dict]:
    url = GREENHOUSE_API.format(board_token=company["board_token"])
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
        location = job.get("location", {}).get("name", "Not specified")
        title = job.get("title", "")
        raw_content = job.get("content", "")
        description = strip_html(raw_content)
        detection_text = full_text(raw_content)
        required_skills = extract_required_skills(title, detection_text)
        normalized.append({
            "source": "greenhouse",
            "source_job_id": f"gh_{job['id']}",
            "title": title,
            "company": company["name"],
            "company_domain": company.get("domain", ""),
            "location": location,
            "description": bake_required_skills(description, required_skills),
            "apply_url": job.get("absolute_url", ""),
            "posted_at": job.get("updated_at", ""),
            "work_type": detect_work_type(title, location, detection_text),
            "experience_level": detect_experience(title, detection_text),
            "required_skills": required_skills,
        })

    return normalized


def main():
    all_jobs = []

    for company in COMPANIES:
        print(f"Fetching jobs for {company['name']}...")
        jobs = fetch_greenhouse_jobs(company)
        all_jobs.extend(jobs)

    print(f"\nTotal jobs fetched: {len(all_jobs)}")

    all_jobs = filter_tech_jobs(all_jobs)
    print(f"After tech filter: {len(all_jobs)}")

    if all_jobs:
        result = save_jobs(all_jobs, source="greenhouse")
        print(f"Saved to MongoDB: {result}")
    else:
        print("No jobs to save.")


if __name__ == "__main__":
    main()
