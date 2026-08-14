"""
One-shot migration: populate `location_tokens` on every existing job.

Introduced 2026-08-14 alongside the switch from case-insensitive regex on
`location` to indexed $all lookups on `location_tokens`. New jobs get the
field on write (see listings/shared/storage.py::save_jobs). Existing jobs
need this backfill — until they have the field, they fall through to the
legacy regex branch in fetch_api/jobs.py::_location_branch, which works
but doesn't use the new index.

Run once, then this script is safe to delete:

    uv run python pipeline/backfill_location_tokens.py

Non-destructive: reads only `location`, writes only `location_tokens`. No
other fields touched.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from pymongo import UpdateOne

from db.mongo import get_db
from listings.shared.storage import _tokenize_location


BATCH_SIZE = 1000


def main() -> None:
    db = get_db()
    collection = db["jobs"]

    total = collection.count_documents({})
    missing = collection.count_documents({"location_tokens": {"$exists": False}})
    print(f"Total jobs: {total}")
    print(f"Jobs missing location_tokens: {missing}")
    if missing == 0:
        print("Nothing to backfill.")
        return

    cursor = collection.find(
        {"location_tokens": {"$exists": False}},
        {"location": 1},
    )

    ops: list[UpdateOne] = []
    written = 0
    processed = 0

    for doc in cursor:
        tokens = _tokenize_location(doc.get("location", ""))
        ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"location_tokens": tokens}}))
        processed += 1
        if len(ops) >= BATCH_SIZE:
            result = collection.bulk_write(ops, ordered=False)
            written += result.modified_count
            ops = []
            print(f"  ...processed {processed}/{missing}", flush=True)

    if ops:
        result = collection.bulk_write(ops, ordered=False)
        written += result.modified_count

    print(f"Processed: {processed}")
    print(f"Updated (modified): {written}")


if __name__ == "__main__":
    main()
