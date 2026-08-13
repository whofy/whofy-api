"""
One-time cleanup: rewrite every job.description that contains the mojibake
sequence "â€¢" (three chars: U+00E2, U+20AC, U+00A2) into the proper bullet
"•" (U+2022).

Root cause fixed in listings/shared/enrich.py (bake_required_skills). This
script backfills rows already saved with the corrupted string. Idempotent:
rows without the mojibake are skipped.

Usage:
    python pipeline/fix_mojibake_bullets.py            # dry run
    python pipeline/fix_mojibake_bullets.py --apply    # actually write
"""
import sys
from pymongo import UpdateOne

from db.mongo import get_client

BAD = "â€¢"   # â€¢
GOOD = "•"              # •


def main(apply: bool) -> int:
    client = get_client()
    coll = client["whofy"]["jobs"]

    query = {"description": {"$regex": BAD}}
    total = coll.count_documents(query)
    print(f"Jobs with mojibake bullets: {total}")
    if total == 0:
        return 0

    ops = []
    for doc in coll.find(query, {"_id": 1, "description": 1}):
        fixed = doc["description"].replace(BAD, GOOD)
        ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"description": fixed}}))

    print(f"Prepared {len(ops)} updates.")
    if not apply:
        print("Dry run — pass --apply to write.")
        return 0

    result = coll.bulk_write(ops, ordered=False)
    print(f"Modified {result.modified_count} documents.")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
