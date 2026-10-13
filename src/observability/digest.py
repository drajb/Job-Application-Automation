"""Daily digest of submissions + responses (sent at 7pm in APPLY_TIMEZONE).

Wired into the daemon via apscheduler (src/observability/scheduler.py). Also
lists rejections and "other" mail, which deliberately don't trigger instant
alerts (docs/SPEC.md §7.3), and the best-performing resume variant.
"""

from __future__ import annotations

import html
import logging
from collections import Counter
from datetime import timedelta

from sqlalchemy import func, select

from src.db.models import Application, ResponseLog
from src.db.session import get_session
from src.orchestrator.preflight import SUBMITTED_STATUSES
from src.util.time import local_day_bounds_utc, local_now, utcnow

log = logging.getLogger(__name__)


def build_digest_text() -> str:
    today = local_now().date()
    t0, t1 = local_day_bounds_utc(today)
    y0, _ = local_day_bounds_utc(today - timedelta(days=1))
    w0, _ = local_day_bounds_utc(today - timedelta(days=6))

    def count(s, start, end=None):
        conds = [Application.status.in_(SUBMITTED_STATUSES), Application.applied_at >= start]
        if end is not None:
            conds.append(Application.applied_at < end)
        return s.scalar(select(func.count(Application.id)).where(*conds)) or 0

    with get_session() as s:
        today_subs = count(s, t0, t1)
        yesterday_subs = count(s, y0, t0)
        week_subs = count(s, w0)
        recent = list(s.scalars(
            select(ResponseLog).where(ResponseLog.classified_at >= utcnow() - timedelta(days=1)),
        ))
        waiting = s.scalar(select(func.count(Application.id)).where(
            Application.status.in_(("handoff", "submit_unverified", "deferred")))) or 0

    cats = Counter(r.category for r in recent)
    high = sum(cats.get(c, 0) for c in ("interview_invite", "recruiter_outreach", "offer"))
    lines = [
        f"📊 <b>Daily digest — {today:%Y-%m-%d}</b>",
        "",
        "<b>Submissions</b>",
        f"  today: {today_subs}",
        f"  yesterday: {yesterday_subs}",
        f"  last 7 days: {week_subs}",
        "",
        "<b>Responses (last 24h)</b>",
        f"  interview / recruiter / offer: {high}",
        f"  rejections: {cats.get('rejection', 0)}",
        f"  confirmations: {cats.get('confirmation', 0)}",
        f"  other: {cats.get('other', 0)}",
    ]
    quiet = [r for r in recent if r.category in ("rejection", "other")][:8]
    if quiet:
        lines += ["", "<b>Quiet mail</b>"]
        lines += [f"  • {html.escape((r.subject or '')[:80])}" for r in quiet]
    if waiting:
        lines += ["", f"⏳ {waiting} application(s) waiting on you — /pending"]

    try:
        from src.observability.rate_tracker import response_rate_by_variant
        stats = [r for r in response_rate_by_variant(window_days=30) if r["submitted"] >= 3]
        if stats:
            best = stats[0]
            lines += ["", f"🏆 Best resume variant (30d): <code>{html.escape(best['variant'])}</code> "
                          f"— {best['rate']:.0%} of {best['submitted']} got a response"]
    except Exception as e:
        log.debug("variant stats unavailable: %s", e)
    return "\n".join(lines)


async def send_daily_digest(telegram) -> None:
    text = build_digest_text()
    if telegram is None or getattr(telegram, "_app", None) is None:
        log.info("[no-telegram] daily digest:\n%s", text)
        return
    await telegram.send_html(text)
