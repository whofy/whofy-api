"""Time cleanup_non_english_jobs() with lang_checked flag."""
from dotenv import load_dotenv
load_dotenv()

import time
from listings.shared.storage import cleanup_non_english_jobs

def time_cleanup():
    print("Run 1: Flagging all existing documents (backfill)...")
    start1 = time.time()
    removed1 = cleanup_non_english_jobs()
    elapsed1 = time.time() - start1
    print(f"  Removed: {removed1}, Elapsed: {elapsed1:.2f}s\n")
    
    print("Run 2: Timing when documents are already flagged...")
    start2 = time.time()
    removed2 = cleanup_non_english_jobs()
    elapsed2 = time.time() - start2
    print(f"  Removed: {removed2}, Elapsed: {elapsed2:.4f}s")

if __name__ == "__main__":
    time_cleanup()
