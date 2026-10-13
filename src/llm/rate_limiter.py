"""Request rate limiter for the Gemini free tier.

Free-tier limits change over time — check https://ai.google.dev/gemini-api/docs/rate-limits
for your model and set GEMINI_RPM / GEMINI_RPD to match. Defaults are the
gemini-2.5-flash free tier at the time of writing (10 RPM / 250 RPD).

What this enforces (docs/SPEC.md §7.6):
  - RPM: hard-throttled — acquire() sleeps until a slot frees up.
  - RPD: soft warn at 80%; hard pause at 95% for normal work (raises so new
    applications stop). `priority=True` callers (signup verification, email
    classification) may use the full 100% daily budget.
  - The daily counter resets at midnight Pacific (when Google resets the
    quota) and is persisted to data/gemini_usage.json, so a restart doesn't
    forget what was already spent today.
  - TPM: recorded per minute for observability via record_success(), not
    enforced — at this call volume the token ceiling is unreachable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

PACIFIC = ZoneInfo("America/Los_Angeles")


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name) or default))
    except ValueError:
        return default


RPM_LIMIT = _env_int("GEMINI_RPM", 10)
RPD_LIMIT = _env_int("GEMINI_RPD", 250)
TPM_LIMIT = 250_000


def _pacific_today() -> date:
    return datetime.now(PACIFIC).date()


class QuotaExhausted(RuntimeError):
    pass


class RateLimiter:
    def __init__(
        self,
        *,
        rpm: int = RPM_LIMIT,
        rpd: int = RPD_LIMIT,
        state_path: Path | None = None,
    ) -> None:
        self.rpm_limit = rpm
        self.rpd_limit = rpd
        self._state_path = state_path
        self._lock = asyncio.Lock()
        self._minute_calls: deque[float] = deque()
        self._minute_tokens: deque[tuple[float, int]] = deque()
        self._day = _pacific_today()
        self._day_calls = 0
        self._soft_warned = False
        self._load()

    # --- persistence ------------------------------------------------------

    def _load(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        try:
            d = json.loads(self._state_path.read_text(encoding="utf-8"))
            if d.get("day") == self._day.isoformat():
                self._day_calls = int(d.get("calls", 0))
        except Exception as e:
            log.debug("rate limiter state unreadable (%s); starting at 0", e)

    def _save(self) -> None:
        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"day": self._day.isoformat(), "calls": self._day_calls}))
            os.replace(tmp, self._state_path)
        except OSError as e:
            log.debug("could not persist rate limiter state: %s", e)

    # --- core -------------------------------------------------------------

    async def acquire(self, *, priority: bool = False) -> None:
        async with self._lock:
            now = time.monotonic()
            self._rollover_day_if_needed()
            self._evict_minute(now)

            cap = self.rpd_limit if priority else int(self.rpd_limit * 0.95)
            if self._day_calls >= cap:
                raise QuotaExhausted(
                    f"daily Gemini quota at hard pause ({self._day_calls}/{self.rpd_limit}). "
                    f"It resets at midnight Pacific time.",
                )
            if self._day_calls >= int(self.rpd_limit * 0.8) and not self._soft_warned:
                log.warning("gemini daily quota at %d/%d (80%%)", self._day_calls, self.rpd_limit)
                self._soft_warned = True

            # RPM: sleep until the oldest call in the window is older than 60s
            while len(self._minute_calls) >= self.rpm_limit:
                wait = max(0.0, 60.0 - (now - self._minute_calls[0]))
                if wait <= 0:
                    self._minute_calls.popleft()
                else:
                    await asyncio.sleep(wait)
                    now = time.monotonic()
                    self._evict_minute(now)

            self._minute_calls.append(now)
            self._day_calls += 1
            self._save()

    def record_success(self, approx_tokens: int) -> None:
        self._minute_tokens.append((time.monotonic(), approx_tokens))

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
        today = _pacific_today()
        if today != self._day:
            log.info("day rollover: resetting Gemini daily counter")
            self._day = today
            self._day_calls = 0
            self._soft_warned = False

    @property
    def day_calls(self) -> int:
        self._rollover_day_if_needed()
        return self._day_calls


@lru_cache(maxsize=1)
def get_rate_limiter() -> RateLimiter:
    """Process-wide singleton limiter.

    Every Gemini call in the process must share ONE limiter, or the RPM/RPD
    counters reset per caller and the free-tier caps enforce nothing. Construct
    the limiter here, not per-application.
    """
    from src.config import DATA_DIR

    raw = os.environ.get("GEMINI_USAGE_FILE")
    path = DATA_DIR / "gemini_usage.json" if raw is None else (Path(raw) if raw else None)
    return RateLimiter(state_path=path)
