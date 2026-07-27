import time
from datetime import datetime, timezone

from listings.greenhouse.fetcher import main as greenhouse_main
from listings.lever.fetcher import main as lever_main
from listings.adzuna.fetcher import main as adzuna_main
from listings.remoteok.fetcher import main as remoteok_main
from listings.ashby.fetcher import main as ashby_main
from listings.scraping.weworkremotely.fetcher import main as wwr_main
from listings.scraping.workday.fetcher import main as workday_main
from listings.himalayas.fetcher import main as himalayas_main
from listings.hackernews.fetcher import main as hackernews_main
from listings.shared.storage import cleanup_expired_jobs, ensure_indexes, get_collection_stats

    

def run_ingestion():
    start = time.time()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n{'='*60}")
    print(f"Whofy Job Ingestion — {ts}")
    print(f"{'='*60}\n")

    ensure_indexes()

    sources = [
        ("Greenhouse", greenhouse_main),
        ("Lever", lever_main),
        ("RemoteOK", remoteok_main),
        ("Adzuna", adzuna_main),
        ("Ashby", ashby_main),
        ("We Work Remotely", wwr_main),
        ("Workday", workday_main),
        ("Himalayas", himalayas_main),
        ("Hacker News", hackernews_main),
    ]

    for name, fetcher in sources:
        print(f"\n--- {name} ---")
        try:
            fetcher()
        except Exception as e:
            print(f"  ERROR in {name}: {e}")

    print(f"\n--- Cleanup ---")
    deleted = cleanup_expired_jobs()
    print(f"Expired jobs removed: {deleted}")

    print(f"\n--- Stats ---")
    stats = get_collection_stats()
    print(f"Total jobs in DB: {stats['total_jobs']}")
    for source, count in stats["per_source"].items():
        print(f"  {source}: {count}")

    elapsed = time.time() - start
    print(f"\nIngestion complete in {elapsed:.1f}s")


if __name__ == "__main__":
    run_ingestion()
