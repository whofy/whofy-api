import threading
import time


class TokenBucket:
    """Thread-safe token bucket for enforcing a real global request rate
    across multiple worker threads.

    All threads sharing one bucket instance are throttled together — three
    threads calling ``acquire()`` on a 1 req/sec bucket produce one request
    per second in aggregate, not three.

    Usage:
        _BUCKET = TokenBucket(rate=1.0)
        _BUCKET.acquire()
        requests.get(...)
    """

    def __init__(self, rate: float, capacity: float | None = None):
        if rate <= 0:
            raise ValueError("rate must be > 0")
        self.rate = rate
        self.capacity = capacity if capacity is not None else max(1.0, rate)
        self.tokens = self.capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self.tokens = min(
                    self.capacity,
                    self.tokens + (now - self._last) * self.rate,
                )
                self._last = now
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return
                wait = (tokens - self.tokens) / self.rate
            time.sleep(wait)
