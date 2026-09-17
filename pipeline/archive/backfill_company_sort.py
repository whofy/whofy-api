"""
One-shot cleanup: populate `company_sort` on every existing job.

Reason: some scraped company names have leading punctuation ("*Strello
Health", ". Crane Worldwide Logistics .") that pollutes ASCII sort — those
rows land ahead of real "A..." companies in "Company (A-Z)". The new
`company_sort` field strips leading non-alphanumerics so sorting behaves the
way a reader expects, while the untouched `company` field is still used for
display.

Ingestion now writes `company_sort` on every save (see
listings/shared/storage.py::save_jobs). This backfill fills it in for the
rows already in the DB.

Run once, then safe to delete:

    uv run python pipeline/backfill_company_sort.py

Non-destructive: reads `company`, writes only `company_sort`. Other fields
untouched.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from pymongo import UpdateOne

from db.mongo import get_db
from listings.shared.storage import _normalize_company_sort


BATCH_SIZE = 1000


def main() -> None:
    db = get_db()
    collection = db["jobs"]

    total = collection.count_documents({})
    print(f"Total jobs: {total}")

    cursor = collection.find({}, {"company": 1, "company_sort": 1})

    ops: list[UpdateOne] = []
    written = 0
    processed = 0

    for doc in cursor:
        processed += 1
        raw = doc.get("company", "")
        new_key = _normalize_company_sort(raw)
        if doc.get("company_sort") == new_key:
            continue
        ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"company_sort": new_key}}))
        if len(ops) >= BATCH_SIZE:
            result = collection.bulk_write(ops, ordered=False)
            written += result.modified_count
            ops = []
            print(f"  ...processed {processed}/{total}", flush=True)

    if ops:
        result = collection.bulk_write(ops, ordered=False)
        written += result.modified_count

    print(f"Processed: {processed}")
    print(f"Updated: {written}")


if __name__ == "__main__":
    main()
