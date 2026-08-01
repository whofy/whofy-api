"""One-time fix: remove duplicate 'Required skills:' blocks from stored
descriptions.  The block was baked in at ingestion, and the old (pre-fix)
API server appended it *again* at runtime — but some docs may also have
been saved with it doubled by a re-ingestion that read an already-baked
description.  This script keeps only the LAST occurrence."""

from dotenv import load_dotenv
load_dotenv()

import re
from pymongo import UpdateOne
from db.mongo import get_db

SKILLS_BLOCK_RE = re.compile(
    r"\n{0,3}Required skills:\n(?:• .+\n?)+",
    re.MULTILINE,
)


def deduplicate(description: str) -> str | None:
    matches = list(SKILLS_BLOCK_RE.finditer(description))
    if len(matches) <= 1:
        return None
    # Keep the last block, strip earlier ones
    for m in matches[:-1]:
        description = description[:m.start()] + description[m.end():]
    return description.strip()


def main():
    db = get_db()
    ops = []
    fixed = 0

    for doc in db.jobs.find({}, {"description": 1}):
        desc = doc.get("description", "")
        cleaned = deduplicate(desc)
        if cleaned is not None:
            ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"description": cleaned}}))
            fixed += 1

    if ops:
        result = db.jobs.bulk_write(ops, ordered=False)
        print(f"Fixed {result.modified_count} of {fixed} docs with duplicate skills blocks.")
    else:
        print("No duplicate skills blocks found in any documents.")


if __name__ == "__main__":
    main()
