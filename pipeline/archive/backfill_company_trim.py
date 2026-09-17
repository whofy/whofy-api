"""
One-shot cleanup: strip leading/trailing whitespace from `company` on every
existing job.

Reason: some sources return company names with a leading space (" Foo Corp").
Space (0x20) sorts before "*" (0x2A) / "." (0x2E) / digits / letters, so a
single " Foo" leaks to position 0 when the user sorts "Company (A-Z)".

Ingestion now trims on write (see listings/shared/storage.py::save_jobs).
This backfill fixes rows already in the DB.

Run once, then this script is safe to delete:

    uv run python pipeline/backfill_company_trim.py

Non-destructive: reads only `company`, writes only `company`. Only rows
where the trimmed value differs are updated.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from pymongo import UpdateOne

from db.mongo import get_db


BATCH_SIZE = 1000


def main() -> None:
    db = get_db()
    collection = db["jobs"]

    total = collection.count_documents({})
    print(f"Total jobs: {total}")

    cursor = collection.find({"company": {"$type": "string"}}, {"company": 1})

    ops: list[UpdateOne] = []
    written = 0
    processed = 0
    dirty = 0

    for doc in cursor:
        processed += 1
        raw = doc.get("company", "")
        trimmed = raw.strip()
        if trimmed == raw:
            continue
        dirty += 1
        ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"company": trimmed}}))
        if len(ops) >= BATCH_SIZE:
            result = collection.bulk_write(ops, ordered=False)
            written += result.modified_count
            ops = []
            print(f"  ...scanned {processed}/{total}, dirty so far: {dirty}", flush=True)

    if ops:
        result = collection.bulk_write(ops, ordered=False)
        written += result.modified_count

    print(f"Scanned: {processed}")
    print(f"Dirty (had leading/trailing whitespace): {dirty}")
    print(f"Updated: {written}")


if __name__ == "__main__":
    main()
