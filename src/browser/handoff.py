"""Stuck detection + Tier-3 escalation glue.

If an adapter spends >stuck_seconds on a single field without progress, raise
StuckError. The orchestrator catches it, calls execution.tier3_handoff.
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


@asynccontextmanager
async def stuck_guard(label: str, *, stuck_seconds: float = 60.0):
    """Yield control. If the body takes > stuck_seconds, raise StuckError."""
    started = time.monotonic()
    task = asyncio.current_task()

    async def _watchdog():
        await asyncio.sleep(stuck_seconds)
        if task is not None and not task.done():
            log.warning("stuck guard tripped on '%s' after %.1fs", label, stuck_seconds)
            task.cancel()

    w = asyncio.create_task(_watchdog())
    try:
        yield
    except asyncio.CancelledError:
        elapsed = time.monotonic() - started
        raise StuckError(label, elapsed) from None
    finally:
        w.cancel()
