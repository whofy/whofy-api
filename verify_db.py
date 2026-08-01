"""Live DB verification: indexes, document counts, sample documents."""
from dotenv import load_dotenv
load_dotenv()

import json
from listings.shared.storage import get_client, DB_NAME

def main():
    client = get_client()
    db = client[DB_NAME]

    # 1. List ALL indexes on jobs collection
    print("=" * 60)
    print("INDEXES ON 'jobs' COLLECTION")
    print("=" * 60)
    indexes = list(db.jobs.list_indexes())
    for i, idx in enumerate(indexes, 1):
        print(f"\n--- Index {i}: {idx['name']} ---")
        print(f"  Key: {dict(idx['key'])}")
        if idx.get("unique"):
            print(f"  Unique: True")
        if "weights" in idx:
            print(f"  Weights: {dict(idx['weights'])}")
        if "default_language" in idx:
            print(f"  Language: {idx['default_language']}")

    print(f"\nTotal indexes: {len(indexes)}")

    # 2. Document counts
    print("\n" + "=" * 60)
    print("DOCUMENT COUNTS")
    print("=" * 60)
    jobs_count = db.jobs.count_documents({})
    print(f"jobs: {jobs_count}")

    saved_jobs_count = db.saved_jobs.count_documents({})
    print(f"saved_jobs: {saved_jobs_count}")

    logos_count = db.company_logos.count_documents({})
    print(f"company_logos: {logos_count}")

    # List ALL collections in the database
    print(f"\nAll collections in '{DB_NAME}':")
    for col_name in sorted(db.list_collection_names()):
        count = db[col_name].estimated_document_count()
        print(f"  {col_name}: ~{count}")

    # 3. Per-source breakdown
    print("\n" + "=" * 60)
    print("PER-SOURCE COUNTS")
    print("=" * 60)
    pipeline = [{"$group": {"_id": "$source", "count": {"$sum": 1}}}]
    for doc in db.jobs.aggregate(pipeline):
        print(f"  {doc['_id']}: {doc['count']}")

    # 4. Sample document shape
    print("\n" + "=" * 60)
    print("SAMPLE DOCUMENT (first job)")
    print("=" * 60)
    sample = db.jobs.find_one()
    if sample:
        sample["_id"] = str(sample["_id"])
        # Truncate description for readability
        if "description" in sample and len(sample.get("description", "")) > 200:
            sample["description"] = sample["description"][:200] + "..."
        print(json.dumps(sample, indent=2, default=str))

    client.close()

if __name__ == "__main__":
    main()
