import threading
import time
from datetime import datetime, timezone

INTERVAL_HOURS = 24
_scheduler_thread = None
_stop_event = threading.Event()


def _run_loop():
    from listings.run_all import run_ingestion

    while not _stop_event.is_set():
        try:
            print(f"\n[Scheduler] Starting ingestion at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
            run_ingestion()
        except Exception as e:
            print(f"[Scheduler] Ingestion error: {e}")

        _stop_event.wait(INTERVAL_HOURS * 3600)


def start_scheduler():
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        print("[Scheduler] Already running.")
        return

    _stop_event.clear()
    _scheduler_thread = threading.Thread(target=_run_loop, daemon=True, name="job-ingestion-scheduler")
    _scheduler_thread.start()
    print(f"[Scheduler] Started — will run every {INTERVAL_HOURS}h")


def stop_scheduler():
    _stop_event.set()
    print("[Scheduler] Stop requested.")
