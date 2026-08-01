import re
import requests
from bs4 import BeautifulSoup

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
url = "https://www.naukri.com/software-engineer-jobs-in-bengaluru"
r = requests.get(url, headers=headers, timeout=30)
print("status", r.status_code, "len", len(r.text))

soup = BeautifulSoup(r.text, "html.parser")
cards = soup.select(".srp-jobtuple-wrapper, .jobTuple, article")
print("cards", len(cards))

scripts = soup.find_all("script", type="application/ld+json")
print("ld+json scripts", len(scripts))

ids = re.findall(r"jobId[\"':]?\s*[\"':]\s*(\d+)", r.text)
print("jobIds count", len(set(ids)), "sample", list(set(ids))[:5])

# look for seoKey patterns
links = soup.select("a.title")
print("title links", len(links))
if links:
    print("first link", links[0].get("href"), links[0].get_text(strip=True))
