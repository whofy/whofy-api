import time
import sys
import threading
import contextvars
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from listings.greenhouse.fetcher import main as greenhouse_main
from listings.lever.fetcher import main as lever_main
from listings.adzuna.fetcher import main as adzuna_main
from listings.remoteok.fetcher import main as remoteok_main
from listings.ashby.fetcher import main as ashby_main
from listings.himalayas.fetcher import main as himalayas_main
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
    try:
        if is_heavy:
            with heavy_semaphore:
                fetcher()
        else:
            fetcher()
    except Exception as e:
        print(f"ERROR in {name}: {e}")
    finally:
        elapsed = time.time() - start_time
        print(f"Completed in {elapsed:.2f} seconds")

def run_ingestion():
    start = time.time()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n{'='*60}")
    print(f"Whofy Job Ingestion (API) — {ts}")
    print(f"{'='*60}\n")

    ensure_indexes()

    sources = [
        ("Greenhouse", greenhouse_main, True),
        ("Lever", lever_main, True),
        ("Ashby", ashby_main, True),
        ("RemoteOK", remoteok_main, False),
        ("Adzuna", adzuna_main, False),
        ("Himalayas", himalayas_main, False),
    ]

    logger = ThreadPrefixLogger()
    sys.stdout = logger
    
    try:
        with ThreadPoolExecutor(max_workers=len(sources)) as executor:
            futures = [executor.submit(run_source_concurrently, name, fetcher, is_heavy) for name, fetcher, is_heavy in sources]
            for future in as_completed(futures):
                future.result()
    finally:
        sys.stdout = logger.original_stdout

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

if __name__ == "__main__":
    run_ingestion()
