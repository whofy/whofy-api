from dotenv import load_dotenv
load_dotenv()

from sources.ats.greenhouse import main as greenhouse_main
from sources.ats.lever import main as lever_main
from sources.aggregator.remoteok import main as remoteok_main
from sources.aggregator.adzuna import main as adzuna_main
from sources.aggregator.jooble import main as jooble_main
from sources.shared.storage import cleanup_expired_jobs, get_collection_stats


def main():
    print("=" * 50)
    print("WHOFY JOB INGESTION")
    print("=" * 50)

    print("\n--- Greenhouse ---")
    greenhouse_main()

    print("\n--- Lever ---")
    lever_main()

    print("\n--- RemoteOK ---")
    remoteok_main()

    print("\n--- Adzuna ---")
    adzuna_main()

    print("\n--- Jooble ---")
    jooble_main()

    print("\n--- Cleanup expired jobs ---")
    deleted = cleanup_expired_jobs()
    print(f"  Removed {deleted} expired jobs")

    print("\n--- Database Stats ---")
    stats = get_collection_stats()
    print(f"Total jobs in DB: {stats['total_jobs']}")
    for source, count in stats["per_source"].items():
        print(f"  {source}: {count}")

    print("\nDone!")


if __name__ == "__main__":
    main()
