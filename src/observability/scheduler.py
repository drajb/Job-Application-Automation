"""APScheduler-driven recurring jobs.

Jobs:
  - daily 7pm CT: digest
  - every 6h: refresh rate stats log
"""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.observability.digest import send_daily_digest

log = logging.getLogger(__name__)

CT = ZoneInfo("America/Chicago")


def start_scheduler(*, telegram=None) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=CT)
    sched.add_job(
        send_daily_digest,
        CronTrigger(hour=19, minute=0, timezone=CT),
        args=[telegram],
        id="daily_digest",
        max_instances=1,
        replace_existing=True,
    )
    sched.start()
    log.info("scheduler started (daily digest @ 7pm CT)")
    return sched
