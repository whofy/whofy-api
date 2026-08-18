"""
One-shot migration: shrink the index footprint of the `jobs` collection.

Measured before writing this (pipeline/audit_indexes.py, 47,089 docs):

    Data on disk    55.7 MB
    Indexes        283.1 MB     <- 84% of the whole database
      of which:
      title_text_description_text   253.5 MB
      company_1__id_1                 2.4 MB   (0 reads, ever)

Two changes:

  1. Drop `company_1__id_1`. The A-Z sort moved to `company_sort` (which
     strips leading punctuation so "*Strello Health" files under S). The old
     index has served zero reads and is updated on every write.

  2. Replace the text index on (title, description) with (title,
     required_skills). /api/search already discards hits that only matched
     the description, so most of what the big index produced was thrown away
     one stage later. required_skills holds the same vocabulary, extracted at
     ingest, in a fraction of the space.

MongoDB allows only one text index per collection, so #2 cannot be done as a
build-then-swap. The old index is dropped first, and `$text` queries —
/api/search and the skill branch of /api/matches — fail until the new one
finishes building. Run it when nobody is using the site.

    uv run python pipeline/migrate_text_index.py --dry-run   # show the plan
    uv run python pipeline/migrate_text_index.py --apply     # do it

Fully reversible. An index is derived from the data, never a copy of record,
so nothing can be lost. To go back:

    db.jobs.dropIndex("title_text_required_skills_text")
    db.jobs.createIndex({title: "text", description: "text"})
    db.jobs.createIndex({company: 1, _id: 1})
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from db.mongo import get_client
from listings.shared.storage import (
    DB_NAME,
    JOBS_COLLECTION,
    TEXT_INDEX_FIELDS,
    _ensure_text_index,
    _existing_text_index,
)

OBSOLETE_INDEXES = ["company_1__id_1"]


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _index_report(db) -> tuple[dict, int]:
    stats = db.command("collStats", JOBS_COLLECTION)
    sizes = stats.get("indexSizes", {})
    return sizes, stats.get("totalIndexSize", sum(sizes.values()))


def main(apply: bool) -> int:
    client = get_client()
    db = client[DB_NAME]
    coll = db[JOBS_COLLECTION]

    sizes_before, total_before = _index_report(db)
    print(f"Index size before: {_human(total_before)}")

    existing = _existing_text_index(coll)
    if existing:
        print(f"  text index '{existing[0]}' covers {sorted(existing[1])} "
              f"({_human(sizes_before.get(existing[0], 0))})")

    present_obsolete = [n for n in OBSOLETE_INDEXES if n in sizes_before]
    for name in present_obsolete:
        print(f"  obsolete index '{name}' ({_human(sizes_before[name])})")

    if not apply:
        print("\nDry run. Would:")
        for name in present_obsolete:
            print(f"  - drop {name}")
        if not existing or existing[1] != set(TEXT_INDEX_FIELDS):
            print(f"  - replace the text index with {sorted(TEXT_INDEX_FIELDS)}")
        else:
            print("  - text index already correct, nothing to do")
        print("\nPass --apply to execute.")
        client.close()
        return 0

    for name in present_obsolete:
        print(f"\nDropping {name}...")
        coll.drop_index(name)

    print("\nSwapping text index (this is the window where $text queries fail)...")
    t0 = time.time()
    _ensure_text_index(coll)
    print(f"Text index rebuilt in {time.time() - t0:.1f}s")

    sizes_after, total_after = _index_report(db)
    print(f"\nIndex size after: {_human(total_after)}")
    print(f"Freed: {_human(total_before - total_after)} "
          f"({(total_before - total_after) / max(total_before, 1) * 100:.0f}%)")

    client.close()
    return 0


if __name__ == "__main__":
    if "--apply" not in sys.argv and "--dry-run" not in sys.argv:
        print(__doc__)
        sys.exit(1)
    sys.exit(main(apply="--apply" in sys.argv))
