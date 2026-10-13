"""APScheduler-driven recurring jobs (all times in APPLY_TIMEZONE).

Jobs:
  - daily 19:00: digest (submissions, responses, quiet mail, best variant)
  - daily SCAN_HOUR (default 9:00): scan the watchlist for new roles and post
    them to Telegram — only when watchlist.yaml exists and Telegram is live.
"""

from __future__ import annotations

import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import LOCAL_TZ
from src.observability.digest import send_daily_digest

log = logging.getLogger(__name__)


def _scan_hour() -> int | None:
    raw = os.environ.get("SCAN_HOUR", "9").strip().lower()
    if raw in ("", "off", "none", "-1"):
        return None
    try:
        h = int(raw)
    except ValueError:
        log.warning("SCAN_HOUR=%r is not an hour; daily scan disabled", raw)
        return None
    return h if 0 <= h <= 23 else None


def start_scheduler(*, telegram=None) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=LOCAL_TZ)
    sched.add_job(
        send_daily_digest,
        CronTrigger(hour=19, minute=0, timezone=LOCAL_TZ),
        args=[telegram],
        id="daily_digest",
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=3600,
    )
    jobs = ["digest @19:00"]

    from src.discovery.watchlist import default_path
    hour = _scan_hour()
    if hour is not None and telegram is not None and default_path().exists():
        sched.add_job(
            telegram.run_scan,
            CronTrigger(hour=hour, minute=0, timezone=LOCAL_TZ),
            id="daily_scan",
            max_instances=1,
            replace_existing=True,
            misfire_grace_time=3600,
        )
        jobs.append(f"watchlist scan @{hour:02d}:00")
    sched.start()
    log.info("scheduler started (%s, %s)", ", ".join(jobs), LOCAL_TZ.key)
    return sched
