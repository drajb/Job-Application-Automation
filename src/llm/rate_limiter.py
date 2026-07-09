"""Request rate limiter for the Gemini free tier.

Free-tier limits (gemini-2.5-flash): 15 RPM, 1,500 RPD, 1M TPM.

What this enforces (docs/SPEC.md §7.6):
  - RPM: hard-throttled — acquire() sleeps until a slot frees up.
  - RPD: soft warn at 80%; hard pause at 95% for normal work (raises so new
    applications stop). `priority=True` callers (signup verification, email
    classification) may use the full 100% daily budget.
  - TPM: recorded per minute for observability via record_success(), but NOT
    hard-enforced — at this call volume (≤15 small calls/min) the 1M token/min
    ceiling is unreachable. tokens_this_minute() exposes the running total if a
    fork wants to add enforcement.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import date
from functools import lru_cache

log = logging.getLogger(__name__)

RPM_LIMIT = 15
RPD_LIMIT = 1500
TPM_LIMIT = 1_000_000


class RateLimiter:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._minute_calls: deque[float] = deque()
        self._minute_tokens: deque[tuple[float, int]] = deque()
        self._day = date.today()
        self._day_calls = 0
        self._soft_warned = False

    async def acquire(self, *, priority: bool = False) -> None:
        async with self._lock:
            now = time.monotonic()
            self._rollover_day_if_needed()
            self._evict_minute(now)

            cap = RPD_LIMIT if priority else int(RPD_LIMIT * 0.95)
            if self._day_calls >= cap:
                raise RuntimeError(
                    f"daily Gemini quota at hard pause ({self._day_calls}/{RPD_LIMIT}). "
                    f"Wait until midnight PT for reset.",
                )
            if self._day_calls >= int(RPD_LIMIT * 0.8) and not self._soft_warned:
                log.warning("gemini daily quota at %d/%d (80%%)", self._day_calls, RPD_LIMIT)
                self._soft_warned = True

            # RPM: sleep until oldest call is older than 60s
            while len(self._minute_calls) >= RPM_LIMIT:
                wait = max(0.0, 60.0 - (now - self._minute_calls[0]))
                if wait <= 0:
                    self._minute_calls.popleft()
                else:
                    await asyncio.sleep(wait)
                    now = time.monotonic()
                    self._evict_minute(now)

            self._minute_calls.append(now)
            self._day_calls += 1

    def record_success(self, approx_tokens: int) -> None:
        now = time.monotonic()
        self._minute_tokens.append((now, approx_tokens))

    def tokens_this_minute(self) -> int:
        """Approx tokens spent in the trailing 60s. For observability/forks."""
        self._evict_minute(time.monotonic())
        return sum(t for _, t in self._minute_tokens)

    def _evict_minute(self, now: float) -> None:
        cutoff = now - 60.0
        while self._minute_calls and self._minute_calls[0] < cutoff:
            self._minute_calls.popleft()
        while self._minute_tokens and self._minute_tokens[0][0] < cutoff:
            self._minute_tokens.popleft()

    def _rollover_day_if_needed(self) -> None:
        today = date.today()
        if today != self._day:
            log.info("day rollover: resetting Gemini daily counter")
            self._day = today
            self._day_calls = 0
            self._soft_warned = False

    @property
    def day_calls(self) -> int:
        return self._day_calls


@lru_cache(maxsize=1)
def get_rate_limiter() -> RateLimiter:
    """Process-wide singleton limiter.

    Every Gemini call in the process must share ONE limiter, or the RPM/RPD
    counters reset per caller and the free-tier caps enforce nothing. Construct
    the limiter here, not per-application.
    """
    return RateLimiter()
