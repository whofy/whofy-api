from dotenv import load_dotenv
load_dotenv()

from sources.shared.storage import cleanup_expired_jobs, get_collection_stats


def main():
    deleted = cleanup_expired_jobs()
    print(f"Removed {deleted} expired jobs")

    stats = get_collection_stats()
    print(f"Total jobs in DB: {stats['total_jobs']}")
    for source, count in stats["per_source"].items():
        print(f"  {source}: {count}")


if __name__ == "__main__":
    main()
