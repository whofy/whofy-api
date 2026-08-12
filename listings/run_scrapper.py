import time
import sys
import threading
import contextvars
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from listings.scraping.weworkremotely.fetcher import main as wwr_main
from listings.scraping.workday.fetcher import main as workday_main
from listings.scraping.linkedin.fetcher import main as linkedin_main
from listings.hackernews.fetcher import main as hackernews_main
from listings.shared.storage import cleanup_expired_jobs, cleanup_non_english_jobs, ensure_indexes, get_collection_stats

# Monkey-patch ThreadPoolExecutor to propagate ContextVars to inner worker threads
_original_submit = ThreadPoolExecutor.submit
def _patched_submit(self, fn, *args, **kwargs):
    context = contextvars.copy_context()
    return _original_submit(self, context.run, fn, *args, **kwargs)
ThreadPoolExecutor.submit = _patched_submit

log_prefix = contextvars.ContextVar('log_prefix', default='')

class ThreadPrefixLogger:
    def __init__(self):
        self.original_stdout = sys.stdout
        self.buffers = {}
        self.lock = threading.Lock()

    def write(self, text):
        prefix = log_prefix.get()
        if not prefix:
            self.original_stdout.write(text)
            return

        ident = threading.get_ident()
        with self.lock:
            if ident not in self.buffers:
                self.buffers[ident] = ""
                
            self.buffers[ident] += text
            if "\n" in self.buffers[ident]:
                lines = self.buffers[ident].split("\n")
                self.buffers[ident] = lines.pop()
                for line in lines:
                    self.original_stdout.write(f"[{prefix}] {line}\n")
            self.original_stdout.flush()

    def flush(self):
        self.original_stdout.flush()

heavy_semaphore = threading.Semaphore(2)

def run_source_concurrently(name, fetcher, is_heavy):
    log_prefix.set(name)
    start_time = time.time()
    print(f"Started fetching at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
    result = {"name": name, "status": "success", "duration": 0.0, "error": None}
    try:
        if is_heavy:
            with heavy_semaphore:
                fetcher()
        else:
            fetcher()
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        print(f"ERROR in {name}: {e}")
    finally:
        result["duration"] = time.time() - start_time
        print(f"Completed in {result['duration']:.2f} seconds")
    return result

def run_ingestion():
    start = time.time()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n{'='*60}")
    print(f"Whofy Job Ingestion (Scrapers) — {ts}")
    print(f"{'='*60}\n")

    ensure_indexes()

    sources = [
        ("Workday", workday_main, True),
        ("We Work Remotely", wwr_main, False),
        # LinkedIn temporarily disabled — takes 20+ minutes and was never brought into the shared MP pipeline optimization; needs proper diagnosis before re-enabling.
        # ("LinkedIn", linkedin_main, False),
        ("Hacker News", hackernews_main, False),
    ]

    logger = ThreadPrefixLogger()
    sys.stdout = logger
    
    results = []
    try:
        with ThreadPoolExecutor(max_workers=len(sources)) as executor:
            futures = [executor.submit(run_source_concurrently, name, fetcher, is_heavy) for name, fetcher, is_heavy in sources]
            for future in as_completed(futures):
                results.append(future.result())
    finally:
        sys.stdout = logger.original_stdout

    print(f"\n--- Source results ---")
    for r in sorted(results, key=lambda x: x["name"]):
        marker = "OK  " if r["status"] == "success" else "FAIL"
        line = f"  [{marker}] {r['name']:15s} ({r['duration']:.1f}s)"
        if r["error"]:
            line += f" — {r['error']}"
        print(line)

    failed = [r for r in results if r["status"] == "failed"]

    if failed:
        print(f"\n{len(failed)} of {len(results)} source(s) FAILED — skipping cleanup to protect data.")
        print(f"Failed: {', '.join(r['name'] for r in failed)}")
    else:
        print(f"\n--- Cleanup ---")
        deleted = cleanup_expired_jobs()
        print(f"Expired jobs removed: {deleted}")
        non_eng = cleanup_non_english_jobs()
        print(f"Non-English jobs removed: {non_eng}")

    print(f"\n--- Stats ---")
    stats = get_collection_stats()
    print(f"Total jobs in DB: {stats['total_jobs']}")
    for source in sorted(stats["per_source"].keys()):
        print(f"  {source}: {stats['per_source'][source]}")

    elapsed = time.time() - start
    print(f"\nIngestion complete in {elapsed:.1f}s")

    if failed:
        print(f"EXIT: FAILURE — {len(failed)} source(s) failed")
        sys.exit(1)

if __name__ == "__main__":
    run_ingestion()
