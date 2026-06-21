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
