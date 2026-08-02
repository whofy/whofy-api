import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pymongo import UpdateOne

from listings.shared.storage import get_client, DB_NAME
LOGOS_COLLECTION = "company_logos_test"

KNOWN_DOMAINS = {
    "google": "google.com",
    "microsoft": "microsoft.com",
    "amazon": "amazon.com",
    "meta": "meta.com",
    "apple": "apple.com",
    "netflix": "netflix.com",
    "uber": "uber.com",
    "airbnb": "airbnb.com",
    "stripe": "stripe.com",
    "shopify": "shopify.com",
    "spotify": "spotify.com",
    "slack": "slack.com",
    "notion": "notion.so",
    "figma": "figma.com",
    "github": "github.com",
    "gitlab": "gitlab.com",
    "atlassian": "atlassian.com",
    "salesforce": "salesforce.com",
    "oracle": "oracle.com",
    "ibm": "ibm.com",
    "intel": "intel.com",
    "nvidia": "nvidia.com",
    "adobe": "adobe.com",
    "twitter": "x.com",
    "linkedin": "linkedin.com",
    "paypal": "paypal.com",
    "razorpay": "razorpay.com",
    "flipkart": "flipkart.com",
    "swiggy": "swiggy.com",
    "zomato": "zomato.com",
    "zerodha": "zerodha.com",
    "freshworks": "freshworks.com",
    "zoho": "zoho.com",
    "infosys": "infosys.com",
    "wipro": "wipro.com",
    "tcs": "tcs.com",
    "hcl": "hcltech.com",
    "cognizant": "cognizant.com",
    "accenture": "accenture.com",
    "deloitte": "deloitte.com",
    "mongodb": "mongodb.com",
    "databricks": "databricks.com",
    "snowflake": "snowflake.com",
    "twilio": "twilio.com",
    "cloudflare": "cloudflare.com",
    "datadog": "datadoghq.com",
    "elastic": "elastic.co",
    "hashicorp": "hashicorp.com",
    "redhat": "redhat.com",
    "vmware": "vmware.com",
    "cisco": "cisco.com",
    "dell": "dell.com",
    "samsung": "samsung.com",
    "sony": "sony.com",
    "bytedance": "bytedance.com",
    "tiktok": "tiktok.com",
    "grab": "grab.com",
    "gojek": "gojek.com",
    "paytm": "paytm.com",
    "phonepe": "phonepe.com",
    "cred": "cred.club",
    "meesho": "meesho.io",
    "unacademy": "unacademy.com",
    "byju": "byjus.com",
    "ola": "olacabs.com",
    "dunzo": "dunzo.com",
    "postman": "postman.com",
    "browserstack": "browserstack.com",
    "hasura": "hasura.io",
    "chargebee": "chargebee.com",
    "clevertap": "clevertap.com",
    "druva": "druva.com",
    "icertis": "icertis.com",
}


def _normalize_company(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _guess_domain(company: str) -> str:
    key = _normalize_company(company)
    if key in KNOWN_DOMAINS:
        return KNOWN_DOMAINS[key]
    slug = re.sub(r"[^a-z0-9]", "", company.lower())
    if not slug:
        return ""
    return f"{slug}.com"


def _check_logo(domain: str) -> str | None:
    url = f"https://logo.clearbit.com/{domain}"
    try:
        resp = requests.head(url, timeout=5, allow_redirects=True)
        if resp.status_code == 200:
            return url
    except requests.RequestException:
        pass
    return None


def _fetch_logo_for_company(company: str, cached: dict) -> tuple[str, str | None]:
    key = _normalize_company(company)
    if key in cached:
        return company, cached[key]

    domain = _guess_domain(company)
    if not domain:
        return company, None

    logo_url = _check_logo(domain)
    return company, logo_url


def attach_logos(jobs: list[dict]) -> int:
    if not jobs:
        return 0

    companies = list({j.get("company", "") for j in jobs if j.get("company")})
    if not companies:
        return 0

    client = get_client()
    db = client[DB_NAME]
    logos_col = db[LOGOS_COLLECTION]

    existing = {}
    for doc in logos_col.find({"company_key": {"$in": [_normalize_company(c) for c in companies]}}):
        existing[doc["company_key"]] = doc.get("logo_url")

    to_fetch = [c for c in companies if _normalize_company(c) not in existing]

    new_logos = {}
    if to_fetch:
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(_fetch_logo_for_company, c, existing): c for c in to_fetch}
            for future in as_completed(futures):
                company, logo_url = future.result()
                key = _normalize_company(company)
                new_logos[key] = logo_url

        ops = []
        for key, logo_url in new_logos.items():
            ops.append(UpdateOne(
                {"company_key": key},
                {"$set": {"company_key": key, "logo_url": logo_url}},
                upsert=True,
            ))
        if ops:
            logos_col.bulk_write(ops, ordered=False)

    all_logos = {**existing, **new_logos}

    attached = 0
    for job in jobs:
        company = job.get("company", "")
        key = _normalize_company(company)
        logo_url = all_logos.get(key)
        if logo_url:
            job["logo_url"] = logo_url
            attached += 1

    return attached
