import os
import time
from collections import deque
from ipaddress import ip_address
from threading import Lock

from fastapi import HTTPException, Request, status

from app.config import load_settings

_MAX_KEYS = 10_000


class RateLimiter:
    """Sliding-window limiter, in-memory.

    ponytail: process-local -- state is lost on restart and not shared across
    machines. Fine for the single Fly machine; use a shared store if we scale out.
    """

    def __init__(self, limit: int, window_seconds: float, clock=time.monotonic,
                 max_keys: int = _MAX_KEYS):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._max_keys = max_keys
        self._lock = Lock()
        self._last_sweep = float("-inf")

    def hit(self, key: str) -> bool:
        """Record an attempt; return False if the key is over its limit."""
        with self._lock:
            now = self._clock()
            # At most one full sweep per window; active keys are never evicted
            # to make room for an attacker rotating identities.
            if now - self._last_sweep >= self.window:
                for k in [k for k, h in self._hits.items()
                          if not h or now - h[-1] >= self.window]:
                    del self._hits[k]
                self._last_sweep = now
            if key not in self._hits:
                if len(self._hits) >= self._max_keys:
                    return False
                self._hits[key] = deque()
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


def client_ip(request: Request) -> str:
    fallback = request.client.host if request.client else "unknown"
    settings = load_settings()
    # Opt-in only on Fly behind its HTTP proxy. Direct/local callers cannot
    # pick their limiter bucket using a supplied forwarding header.
    if (
        settings.trust_fly_client_ip
        and settings.app_env == "production"
        and os.getenv("FLY_APP_NAME")
    ):
        try:
            return str(ip_address(request.headers.get("fly-client-ip", "")))
        except ValueError:
            pass
    return fallback


def enforce(limiter: RateLimiter, *keys: str) -> None:
    # Check every key (no short-circuit) so each counts the attempt.
    allowed = [limiter.hit(k) for k in keys]
    if not all(allowed):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts. Try again later."
        )
