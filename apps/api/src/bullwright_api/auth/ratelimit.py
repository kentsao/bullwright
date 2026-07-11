"""Per-key sliding-window rate limiter (rule S6). In-memory: correct for
the single-process MVP; the interface survives a Redis swap in cloud."""

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key_id: str, bucket: str, limit: int, window_s: float = 60.0) -> float:
        """Record one event. Returns 0.0 if allowed, else seconds until
        the caller may retry (for the Retry-After header)."""
        now = time.monotonic()
        with self._lock:
            q = self._events[(key_id, bucket)]
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                return max(0.1, q[0] + window_s - now)
            q.append(now)
            return 0.0

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


limiter = SlidingWindowLimiter()
