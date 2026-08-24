"""Daily 7pm CT digest of submissions + responses.

Wired into the main.py event loop via apscheduler. The scheduler is
optional — without it, the daily digest can be triggered via /status.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from src.db.models import Application, ResponseLog
from src.db.session import get_session
from src.util.time import utcnow

log = logging.getLogger(__name__)
CT = ZoneInfo("America/Chicago")


def build_digest_text() -> str:
    today = datetime.now(CT).date()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)

    with get_session() as s:
        today_subs = s.scalar(
            select(func.count(Application.id)).where(
                func.date(Application.applied_at) == today,
            ),
        ) or 0
        yesterday_subs = s.scalar(
            select(func.count(Application.id)).where(
                func.date(Application.applied_at) == yesterday,
            ),
        ) or 0
        week_subs = s.scalar(
            select(func.count(Application.id)).where(
                Application.applied_at >= datetime(week_ago.year, week_ago.month, week_ago.day),
            ),
        ) or 0
        recent_responses = list(s.scalars(
            select(ResponseLog).where(
                ResponseLog.classified_at >= utcnow() - timedelta(days=1),
            ),
        ))

    cats = Counter(r.category for r in recent_responses)
    rejection_count = cats.get("rejection", 0)
    other_count = cats.get("other", 0)
    high = sum(cats.get(c, 0) for c in ("interview_invite", "recruiter_outreach", "offer"))

    text = (
        f"📊 *Daily digest — {today:%Y-%m-%d}*\n\n"
        f"*Submissions:*\n"
        f"  today: {today_subs}\n"
        f"  yesterday: {yesterday_subs}\n"
        f"  last 7 days: {week_subs}\n\n"
        f"*Responses (last 24h):*\n"
        f"  interview/recruiter/offer: {high}\n"
        f"  rejections: {rejection_count}\n"
        f"  other: {other_count}\n"
    )
    return text


async def send_daily_digest(telegram) -> None:
    text = build_digest_text()
    if telegram is None or not telegram.configured() or telegram._app is None:
        log.info("[no-telegram] daily digest:\n%s", text)
        return
    await telegram._app.bot.send_message(
        chat_id=telegram.settings.telegram_chat_id,
        text=text,
    )
