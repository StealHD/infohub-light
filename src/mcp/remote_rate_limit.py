"""Per-delegation Remote MCP call limiting."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class DelegationRateLimiter:
    """In-process token bucket: 60 calls/minute with a burst of 10."""

    def __init__(
        self,
        *,
        rate_per_minute: int = 60,
        burst: int = 10,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.refill_per_second = float(rate_per_minute) / 60.0
        self.burst = float(burst)
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            tokens, previous = self._buckets.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - previous) * self.refill_per_second)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True
