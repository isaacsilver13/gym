import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class RateLimiter:
    """Sliding-window limiter, in-memory.

    ponytail: process-local -- state is lost on restart and not shared across
    machines. Fine for the single Fly machine; use a shared store if we scale out.
    """

    def __init__(self, limit: int, window_seconds: float, clock=time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> bool:
        """Record an attempt; return False if the key is over its limit."""
        now = self._clock()
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if not hits:
            # drop idle keys so the dict can't grow without bound
            self._hits.pop(key, None)
            hits = self._hits[key]
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


def client_ip(request: Request) -> str:
    # Fly's proxy puts the real client first in Fly-Client-IP.
    fallback = request.client.host if request.client else "unknown"
    return request.headers.get("fly-client-ip") or fallback


def enforce(limiter: RateLimiter, *keys: str) -> None:
    # Check every key (no short-circuit) so each counts the attempt.
    allowed = [limiter.hit(k) for k in keys]
    if not all(allowed):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts. Try again later."
        )
