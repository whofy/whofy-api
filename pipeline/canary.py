"""
Weekly source canary — pings each ingestion source with the smallest probe
possible and asserts the response is healthy.

Purpose: catch silent breakage (source returns 0 jobs, changes URL, changes
data shape) weeks before the daily ingestion accumulates missing data.

Exits with non-zero when any source fails so GitHub Actions marks the run
red → repo watchers get an email.

Only probes API-based sources. Scrapers (Workday/WWR/HN/LinkedIn) are too
heavy for a weekly heartbeat.
"""
import os
import sys
import time

import requests

HEADERS = {
    "User-Agent": "Whofy Job Aggregator canary (contact: whofyteam@gmail.com)"
}

TIMEOUT = 20
MIN_JOBS = 1  # a healthy probe should return at least this many jobs


class ProbeFailure(Exception):
    pass


def _get_json(url: str, params: dict | None = None) -> dict | list:
    resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise ProbeFailure(f"HTTP {resp.status_code} from {url}")
    return resp.json()


def probe_greenhouse() -> int:
    """Anthropic reliably has open roles — good stable canary target."""
    data = _get_json("https://boards-api.greenhouse.io/v1/boards/anthropic/jobs")
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    if len(jobs) < MIN_JOBS:
        raise ProbeFailure(f"only {len(jobs)} jobs (expected ≥ {MIN_JOBS})")
    if not jobs[0].get("title"):
        raise ProbeFailure("first job missing 'title' — schema drift?")
    return len(jobs)


def probe_lever() -> int:
    data = _get_json("https://api.lever.co/v0/postings/spotify?mode=json")
    if not isinstance(data, list):
        raise ProbeFailure(f"expected list, got {type(data).__name__}")
    if len(data) < MIN_JOBS:
        raise ProbeFailure(f"only {len(data)} jobs")
    if not data[0].get("text"):
        raise ProbeFailure("first job missing 'text' field — schema drift?")
    return len(data)


def probe_ashby() -> int:
    data = _get_json("https://api.ashbyhq.com/posting-api/job-board/openai")
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    if len(jobs) < MIN_JOBS:
        raise ProbeFailure(f"only {len(jobs)} jobs")
    if not jobs[0].get("title"):
        raise ProbeFailure("first job missing 'title' — schema drift?")
    return len(jobs)


def probe_remoteok() -> int:
    data = _get_json("https://remoteok.com/api")
    # First element is the legal notice header; jobs follow.
    if not isinstance(data, list) or len(data) < 2:
        raise ProbeFailure(f"response too small: {len(data) if isinstance(data, list) else 'not a list'}")
    jobs = [j for j in data if isinstance(j, dict) and j.get("id")]
    if len(jobs) < MIN_JOBS:
        raise ProbeFailure(f"only {len(jobs)} jobs")
    if not jobs[0].get("position"):
        raise ProbeFailure("first job missing 'position' — schema drift?")
    return len(jobs)


def probe_himalayas() -> int:
    data = _get_json(
        "https://himalayas.app/jobs/api",
        params={"limit": 10, "offset": 0},
    )
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    if len(jobs) < MIN_JOBS:
        raise ProbeFailure(f"only {len(jobs)} jobs")
    if not jobs[0].get("title"):
        raise ProbeFailure("first job missing 'title' — schema drift?")
    return len(jobs)


def probe_adzuna() -> int:
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise ProbeFailure("ADZUNA_APP_ID / ADZUNA_APP_KEY not set")
    data = _get_json(
        "https://api.adzuna.com/v1/api/jobs/us/search/1",
        params={
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": 10,
            "what": "software engineer",
            "category": "it-jobs",
        },
    )
    results = data.get("results", []) if isinstance(data, dict) else []
    if len(results) < MIN_JOBS:
        raise ProbeFailure(f"only {len(results)} jobs")
    if not results[0].get("title"):
        raise ProbeFailure("first job missing 'title' — schema drift?")
    return len(results)


PROBES = {
    "greenhouse": probe_greenhouse,
    "lever": probe_lever,
    "ashby": probe_ashby,
    "remoteok": probe_remoteok,
    "himalayas": probe_himalayas,
    "adzuna": probe_adzuna,
}


def _run_probe_with_retry(name: str, fn, attempts: int = 2, backoff: float = 3.0):
    last_err = None
    for i in range(1, attempts + 1):
        try:
            count = fn()
            return ("ok", count, None)
        except Exception as e:
            last_err = e
            if i < attempts:
                time.sleep(backoff)
    return ("fail", 0, last_err)


def main() -> int:
    print("=== Whofy source canary ===")
    results = []
    for name, fn in PROBES.items():
        status, count, err = _run_probe_with_retry(name, fn)
        results.append((name, status, count, err))
        if status == "ok":
            print(f"[OK  ] {name:<12} → {count} jobs")
        else:
            print(f"[FAIL] {name:<12} → {type(err).__name__}: {err}")

    failed = [r for r in results if r[1] == "fail"]
    print(f"\nSummary: {len(results) - len(failed)}/{len(results)} sources healthy")

    if failed:
        print("\nFailed probes:")
        for name, _, _, err in failed:
            print(f"  - {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
