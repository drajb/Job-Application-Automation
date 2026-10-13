"""Stuck detection + Tier-3 escalation glue.

`stuck_guard` cancels the body if it runs longer than `stuck_seconds` of
ACTIVE time and turns that into StuckError; the orchestrator catches it and
hands the browser to a human (execution.tier3_handoff).

Time spent waiting on the human (a Telegram question) is not "stuck" — wrap
those waits in `guard.paused()` so the watchdog stops the clock.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

log = logging.getLogger(__name__)


class StuckError(RuntimeError):
    def __init__(self, where: str, seconds: float) -> None:
        super().__init__(f"stuck on '{where}' for {seconds:.1f}s")
        self.where = where
        self.seconds = seconds


class _Guard:
    def __init__(self, label: str, stuck_seconds: float) -> None:
        self.label = label
        self.stuck_seconds = stuck_seconds
        self.active = 0.0  # accumulated un-paused seconds
        self._since: float | None = time.monotonic()
        self._pauses = 0
        self.tripped = False

    def elapsed(self) -> float:
        extra = (time.monotonic() - self._since) if self._since is not None else 0.0
        return self.active + extra

    @asynccontextmanager
    async def paused(self):
        """Stop the clock while waiting on a human."""
        if self._pauses == 0 and self._since is not None:
            self.active += time.monotonic() - self._since
            self._since = None
        self._pauses += 1
        try:
            yield
        finally:
            self._pauses -= 1
            if self._pauses == 0:
                self._since = time.monotonic()


@asynccontextmanager
async def stuck_guard(label: str, *, stuck_seconds: float = 60.0):
    """Yield a guard. If the body is active > stuck_seconds, raise StuckError.

    A cancellation that did NOT come from this guard (e.g. shutdown) is
    re-raised untouched.
    """
    guard = _Guard(label, stuck_seconds)
    task = asyncio.current_task()

    async def _watchdog():
        while True:
            remaining = guard.stuck_seconds - guard.elapsed()
            if remaining <= 0 and guard._pauses == 0:
                break
            await asyncio.sleep(max(0.05, min(remaining, 1.0)) if remaining > 0 else 0.5)
        if task is not None and not task.done():
            log.warning("stuck guard tripped on '%s' after %.1fs", label, guard.elapsed())
            guard.tripped = True
            task.cancel()

    w = asyncio.create_task(_watchdog())
    try:
        yield guard
    except asyncio.CancelledError:
        if not guard.tripped:
            raise
        if task is not None and hasattr(task, "uncancel"):
            task.uncancel()
        raise StuckError(label, guard.elapsed()) from None
    finally:
        w.cancel()
