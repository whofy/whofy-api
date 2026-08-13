import threading
import time

import pytest

from listings.shared.rate_limiter import TokenBucket


def test_rejects_non_positive_rate():
    with pytest.raises(ValueError):
        TokenBucket(rate=0)
    with pytest.raises(ValueError):
        TokenBucket(rate=-1)


def test_burst_up_to_capacity_is_instant():
    bucket = TokenBucket(rate=10, capacity=5)
    start = time.monotonic()
    for _ in range(5):
        bucket.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.05, f"burst should be near-instant, took {elapsed:.3f}s"


def test_enforces_rate_after_burst_drained():
    bucket = TokenBucket(rate=10, capacity=1)  # 1 token, refills at 10/s
    bucket.acquire()  # drain
    start = time.monotonic()
    bucket.acquire()  # must wait ~0.1s
    elapsed = time.monotonic() - start
    assert 0.05 <= elapsed <= 0.25, f"expected ~0.1s wait, got {elapsed:.3f}s"


def test_shared_bucket_across_threads_enforces_global_rate():
    """The core F-15 guarantee: N threads sharing one bucket produce the
    bucket's global rate, not N × per-thread rate."""
    bucket = TokenBucket(rate=10, capacity=1)  # 10 req/sec, burst of 1
    bucket.acquire()  # drain initial burst

    call_count = 20
    threads_n = 4
    per_thread = call_count // threads_n

    def worker():
        for _ in range(per_thread):
            bucket.acquire()

    start = time.monotonic()
    threads = [threading.Thread(target=worker) for _ in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - start

    # 20 tokens at 10/s = ~2s regardless of thread count.
    # Without the bucket, 4 threads would finish in <0.1s.
    assert 1.5 <= elapsed <= 3.0, (
        f"4 threads × 5 calls @ shared 10/sec should take ~2s, got {elapsed:.3f}s"
    )
