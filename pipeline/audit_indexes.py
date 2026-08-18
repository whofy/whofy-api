"""
Index audit: what each index costs, and whether anything actually uses it.

Read-only. Issues `collStats` and `$indexStats` and prints a table. Nothing
is created, dropped, or modified.

    uv run python pipeline/audit_indexes.py

Reading the "Reads" column: it comes from $indexStats, which counts index
accesses **since the server last started**. On Atlas shared tiers the server
restarts periodically, so a 0 does not prove an index is never used — it
proves it hasn't been used since the last restart. Check twice, days apart,
before dropping anything on the strength of it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from db.mongo import get_client
from listings.shared.storage import DB_NAME, JOBS_COLLECTION


def _human(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def audit_collection(db, name: str) -> None:
    coll = db[name]
    try:
        stats = db.command("collStats", name)
    except Exception as e:
        print(f"  ({name}: collStats unavailable — {type(e).__name__}: {e})")
        return

    docs = stats.get("count", 0)
    data_size = stats.get("size", 0)
    index_sizes = stats.get("indexSizes", {})
    total_index = stats.get("totalIndexSize", sum(index_sizes.values()))

    print(f"\n=== {name} ===")
    print(f"  Documents:   {docs:,}")
    print(f"  Data size:   {_human(data_size)}")
    print(f"  Index size:  {_human(total_index)}", end="")
    if data_size:
        print(f"   ({total_index / data_size * 100:.0f}% of data size)")
    else:
        print()

    # Usage counters, keyed by index name.
    usage = {}
    try:
        for row in coll.aggregate([{"$indexStats": {}}]):
            usage[row["name"]] = row.get("accesses", {}).get("ops", 0)
    except Exception as e:
        print(f"  ($indexStats unavailable — {type(e).__name__})")

    keys_by_name = {idx["name"]: dict(idx["key"]) for idx in coll.list_indexes()}

    print(f"\n  {'Index':<38} {'Size':>10} {'Reads':>12}")
    print(f"  {'-' * 38} {'-' * 10} {'-' * 12}")

    rows = sorted(index_sizes.items(), key=lambda kv: kv[1], reverse=True)
    unused = []
    for idx_name, size in rows:
        reads = usage.get(idx_name)
        reads_str = f"{reads:,}" if reads is not None else "n/a"
        print(f"  {idx_name[:38]:<38} {_human(size):>10} {reads_str:>12}")
        if reads == 0 and idx_name != "_id_":
            unused.append((idx_name, size, keys_by_name.get(idx_name)))

    if unused:
        wasted = sum(s for _, s, _ in unused)
        print(f"\n  {len(unused)} index(es) with zero reads since last restart, "
              f"costing {_human(wasted)}:")
        for idx_name, size, keys in unused:
            print(f"    - {idx_name}  {keys}  ({_human(size)})")
        print("\n  Every write updates these. See the docstring before acting on a 0.")


def audit():
    client = get_client()
    db = client[DB_NAME]

    print("=== Whofy index audit (read-only) ===")
    try:
        db_stats = db.command("dbStats")
        print(f"\nDatabase '{DB_NAME}':")
        print(f"  Storage used: {_human(db_stats.get('storageSize', 0))}")
        print(f"  Indexes:      {_human(db_stats.get('indexSize', 0))}")
    except Exception as e:
        print(f"(dbStats unavailable — {type(e).__name__}: {e})")

    for name in (JOBS_COLLECTION, "saved_jobs", "ingestion_rejections"):
        if name in db.list_collection_names():
            audit_collection(db, name)

    client.close()


if __name__ == "__main__":
    audit()
