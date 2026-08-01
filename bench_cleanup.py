"""Time cleanup_non_english_jobs() in isolation against the live DB."""
from dotenv import load_dotenv
load_dotenv()

import time
from listings.shared.storage import get_client, DB_NAME, JOBS_COLLECTION

def time_cleanup():
    client = get_client()
    db = client[DB_NAME]
    collection = db[JOBS_COLLECTION]

    total = collection.count_documents({})
    print(f"Total documents in DB: {total}")

    # -- Time the EXISTING implementation (but don't actually delete — dry run) --
    try:
        from langdetect import detect, LangDetectException, DetectorFactory
        DetectorFactory.seed = 0
    except ImportError:
        print("langdetect not installed")
        return

    start = time.time()
    non_english_ids = []
    checked = 0
    for doc in collection.find({}, {"title": 1, "description": 1}):
        title = doc.get("title", "")
        desc = doc.get("description", "")[:500]
        text = f"{title} {desc}".strip()
        if not text:
            checked += 1
            continue
        try:
            lang = detect(text)
            if lang != "en":
                non_english_ids.append(doc["_id"])
        except Exception:
            pass
        checked += 1
        if checked % 5000 == 0:
            print(f"  checked {checked}/{total} ({len(non_english_ids)} non-English so far) [{time.time()-start:.1f}s]")

    elapsed = time.time() - start
    print(f"\nDry run complete:")
    print(f"  Checked: {checked} documents")
    print(f"  Non-English found: {len(non_english_ids)}")
    print(f"  Elapsed: {elapsed:.2f}s")
    print(f"  Per doc: {elapsed/max(checked,1)*1000:.2f}ms")
    client.close()

if __name__ == "__main__":
    time_cleanup()
