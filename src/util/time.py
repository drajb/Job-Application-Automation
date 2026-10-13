"""Time helpers.

`utcnow()` returns a naive UTC datetime — same shape as the now-deprecated
`datetime.utcnow()` but using the modern non-deprecated API. We keep things
naive because the SQLAlchemy `DateTime` columns in `src/db/models.py` are
naive; mixing tz-aware and naive datetimes inside comparisons silently
returns wrong rows.

If you need a tz-aware datetime (e.g. for cron expressions or window
comparisons), call `datetime.now(timezone.utc)` directly at the use site.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return naive UTC datetime. Drop-in replacement for `datetime.utcnow()`."""
    return datetime.now(UTC).replace(tzinfo=None)


def local_tz():
    """The user's timezone (APPLY_TIMEZONE, default America/Chicago)."""
    from src.config import LOCAL_TZ

    return LOCAL_TZ


def local_now() -> datetime:
    """tz-aware 'now' in the user's timezone."""
    return datetime.now(local_tz())


def local_day_bounds_utc(day=None) -> tuple[datetime, datetime]:
    """[start, end) of a LOCAL calendar day, as naive UTC — for comparing with
    DB columns (which store naive UTC). Defaults to today."""
    from datetime import time, timedelta

    tz = local_tz()
    day = day or local_now().date()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return (
        start.astimezone(UTC).replace(tzinfo=None),
        end.astimezone(UTC).replace(tzinfo=None),
    )
