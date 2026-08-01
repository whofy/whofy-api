"""Time cleanup_non_english_jobs() real run."""
from dotenv import load_dotenv
load_dotenv()

import time
from listings.shared.storage import cleanup_non_english_jobs

def time_cleanup():
    print("Running optimized cleanup_non_english_jobs()...")
    start = time.time()
    
    removed = cleanup_non_english_jobs()
    
    elapsed = time.time() - start
    print(f"\nReal run complete:")
    print(f"  Non-English found and removed: {removed}")
    print(f"  Elapsed: {elapsed:.2f}s")

if __name__ == "__main__":
    time_cleanup()
