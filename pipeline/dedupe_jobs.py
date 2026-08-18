"""
Cross-source job deduplication.

Same real-world job posted on multiple boards (e.g., an Anthropic role
appearing on both Greenhouse and Ashby) currently lives as multiple rows
in the `jobs` collection. This script groups by `canonical_fingerprint`,
keeps ONE canonical copy per group (from the highest-priority source),
and deletes the rest.

Runs automatically after every daily ingestion via the GitHub Actions
workflow. Also runnable manually:

    uv run python pipeline/dedupe_jobs.py

Non-destructive to legacy docs: if any existing jobs don't yet have a
`canonical_fingerprint` field (from before this script was added), they
get backfilled in-place first.

Note: `saved_jobs` records pointing to a deleted duplicate will show as
"expired" via the existing snapshot fallback in fetch_api/saved_jobs.py.
Redirecting saved_jobs to survivors is deliberately not implemented here
(rare edge case, and the snapshot fallback keeps the UI graceful).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from pymongo import UpdateOne

from db.mongo import get_db
from listings.shared.storage import _canonical_fingerprint


# Higher-quality sources ranked FIRST (lower number = keep this copy).
# Direct-from-ATS sources beat aggregators; aggregators are last because
# their descriptions/apply URLs are re-scraped and often lower-fidelity.
SOURCE_PRIORITY = {
    "greenhouse": 1,
    "ashby":      2,
    "lever":      3,
    "workday":    4,
    "himalayas":  5,
    "hackernews": 6,
    "weworkremotely": 7,
    "remoteok":   8,
    "adzuna":     9,
}

_UNKNOWN_SOURCE_PRIORITY = 99


def backfill_missing_fingerprints(db) -> int:
    """One-time: compute canonical_fingerprint for pre-existing docs."""
    missing = db.jobs.count_documents({"canonical_fingerprint": {"$exists": False}})
    if missing == 0:
        return 0

    print(f"Backfilling canonical_fingerprint for {missing} legacy jobs...")
    ops: list[UpdateOne] = []
    batch_size = 1000
    written = 0

    cursor = db.jobs.find(
        {"canonical_fingerprint": {"$exists": False}},
        {"company": 1, "title": 1, "location": 1},
    )
    for doc in cursor:
        fp = _canonical_fingerprint(
            doc.get("company", ""),
            doc.get("title", ""),
            doc.get("location", ""),
        )
        ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"canonical_fingerprint": fp}}))
        if len(ops) >= batch_size:
            result = db.jobs.bulk_write(ops, ordered=False)
            written += result.modified_count
            ops = []

    if ops:
        result = db.jobs.bulk_write(ops, ordered=False)
        written += result.modified_count

    print(f"Backfilled {written} docs.")
    return written


def dedupe(db, dry_run: bool = False) -> tuple[int, int]:
    """
    Find groups of jobs sharing the same canonical_fingerprint, keep the
    highest-priority-source copy, delete the rest. Returns (groups, deleted).

    CROSS-SOURCE ONLY. canonical_fingerprint is normalized(company + title +
    location) — it carries no notion of *which posting* a row is. A large
    employer routinely has several distinct open requisitions with the same
    title in the same location (different teams, different reqs, different
    apply URLs), and on a single board those are separate jobs with separate
    source_job_ids. Grouping on the fingerprint alone treated them as
    duplicates and deleted all but one — every night, re-deleting them after
    each ingestion re-added them.

    So a group only qualifies when it spans 2+ sources, and within a
    qualifying group we only delete rows from the *losing* sources. Rows
    sharing the winner's source are left alone: that source already told us
    they're distinct postings by giving them distinct ids.
    """
    pipeline = [
        {"$match": {"canonical_fingerprint": {"$exists": True, "$ne": ""}}},
        {"$group": {
            "_id": "$canonical_fingerprint",
            "docs": {"$push": {
                "_id": "$_id",
                "source": "$source",
                "last_seen_at": "$last_seen_at",
            }},
            "count": {"$sum": 1},
            "sources": {"$addToSet": "$source"},
        }},
        # count > 1 alone is not enough — that also matches intra-source
        # groups, which are legitimately distinct jobs.
        {"$match": {
            "count": {"$gt": 1},
            "$expr": {"$gt": [{"$size": "$sources"}, 1]},
        }},
    ]

    to_delete: list = []
    groups = 0

    for group in db.jobs.aggregate(pipeline, allowDiskUse=True):
        groups += 1
        docs = group["docs"]

        # Sort: preferred source first, then most recently seen (tie-breaker).
        def _key(d):
            src_pri = SOURCE_PRIORITY.get(d.get("source", ""), _UNKNOWN_SOURCE_PRIORITY)
            last_seen = d.get("last_seen_at")
            # Sort by (source priority ASC, last_seen DESC): lower priority number
            # is better, later last_seen is better.
            last_seen_ts = -last_seen.timestamp() if last_seen else 0
            return (src_pri, last_seen_ts)

        docs.sort(key=_key)
        # docs[0] is the winner. Everything from a DIFFERENT source is a
        # cross-source duplicate and gets deleted; anything sharing the
        # winner's source is a separate requisition and stays.
        winner_source = docs[0].get("source")
        for loser in docs[1:]:
            if loser.get("source") != winner_source:
                to_delete.append(loser["_id"])

    if not to_delete:
        return groups, 0

    if dry_run:
        print(f"[dry-run] {groups} cross-source groups; would remove {len(to_delete)} rows. Nothing written.")
        return groups, 0

    print(f"Found {groups} cross-source duplicate groups; removing {len(to_delete)} redundant rows...")
    chunk_size = 1000
    deleted = 0
    for i in range(0, len(to_delete), chunk_size):
        chunk = to_delete[i:i + chunk_size]
        result = db.jobs.delete_many({"_id": {"$in": chunk}})
        deleted += result.deleted_count

    return groups, deleted


def main(dry_run: bool = False):
    db = get_db()
    total_before = db.jobs.count_documents({})
    print(f"Total jobs before dedupe: {total_before}")
    if dry_run:
        print("DRY RUN — no documents will be deleted.")

    if dry_run:
        # The backfill writes, so it's skipped here. Legacy docs without a
        # fingerprint simply won't appear in the dry-run grouping.
        missing = db.jobs.count_documents({"canonical_fingerprint": {"$exists": False}})
        print(f"[dry-run] skipping backfill of {missing} legacy docs (writes disabled)")
    else:
        backfill_missing_fingerprints(db)

    groups, deleted = dedupe(db, dry_run=dry_run)

    total_after = db.jobs.count_documents({})
    print(f"\nDedupe summary:")
    print(f"  Duplicate groups: {groups}")
    print(f"  Rows deleted:     {deleted}")
    print(f"  Total before:     {total_before}")
    print(f"  Total after:      {total_after}")
    print(f"  Reduction:        {total_before - total_after} ({(total_before - total_after) / max(total_before, 1) * 100:.1f}%)")


if __name__ == "__main__":
    # Default stays destructive so the CI workflow is unchanged; pass
    # --dry-run to see what would be removed without writing.
    main(dry_run="--dry-run" in sys.argv)
