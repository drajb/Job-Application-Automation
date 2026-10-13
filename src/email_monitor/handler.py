"""Top-level on_message handler. Glues correlator + classifier + matcher.

Wired into imap_idle.listen(settings, on_message=handle).
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from src.config import Settings
from src.db.models import Application, ResponseLog
from src.db.session import get_session
from src.email_monitor.classifier import HIGH_PRIORITY, classify
from src.email_monitor.imap_idle import IncomingEmail
from src.email_monitor.matcher import match
from src.email_monitor.signup_correlator import match_and_fulfill
from src.util.time import utcnow

log = logging.getLogger(__name__)

# Response category → application status (only ever moves "forward").
_STATUS_FOR = {"interview_invite": "interview", "offer": "offer", "rejection": "rejected_by_company",
               "recruiter_outreach": "response"}
_RANK = {"submitted": 0, "submit_unverified": 0, "response": 1, "rejected_by_company": 1,
         "interview": 2, "offer": 3}


async def make_handler(settings: Settings, telegram=None):
    """Return an async on_message(IncomingEmail) callback."""

    async def handle(msg: IncomingEmail) -> None:
        # 0) Already processed (e.g. the \\Seen flag failed last time)?
        with get_session() as s:
            dup = s.scalar(select(ResponseLog.id).where(
                ResponseLog.email_uid == msg.uid, ResponseLog.from_addr == msg.from_addr,
                ResponseLog.subject == msg.subject,
            ).limit(1))
        if dup is not None:
            log.info("email uid=%s already logged (#%s); skipping", msg.uid, dup)
            return

        # 1) Try to fulfill a signup expectation first (fast, no LLM cost).
        if (eid := match_and_fulfill(msg)) is not None:
            log.info("email handled as signup fulfillment (#%s)", eid)
            return

        # 2) Classify as response (Gemini, or keyword fallback).
        cls = await classify(msg, settings=settings)

        # 3) Match to an application (best-effort).
        app = match(msg)
        app_id = app.id if app else None

        with get_session() as s:
            row = ResponseLog(
                application_id=app_id,
                email_uid=msg.uid,
                from_addr=msg.from_addr,
                subject=msg.subject,
                body_excerpt=(msg.body_text or "")[:1200],
                category=cls.category,
                classified_at=utcnow(),
                notified=False,
            )
            s.add(row)
            if app_id is not None and cls.category in _STATUS_FOR:
                a = s.get(Application, app_id)
                new = _STATUS_FOR[cls.category]
                if a is not None and _RANK.get(new, 0) >= _RANK.get(a.status or "", 0):
                    a.status = new
                    a.response_at = a.response_at or utcnow()
            s.commit()
            row_id = row.id

        # 4) Notify if high priority.
        if cls.category in HIGH_PRIORITY:
            sent = await _alert(telegram, app, msg, cls)
            if sent:
                with get_session() as s:
                    rl = s.get(ResponseLog, row_id)
                    if rl is not None:
                        rl.notified = True
                        s.commit()
        else:
            log.info(
                "response logged silently: category=%s app=%s subject=%r",
                cls.category, app_id, msg.subject[:60],
            )

    return handle


async def _alert(telegram, app, msg: IncomingEmail, cls) -> bool:
    if telegram is None or getattr(telegram, "_app", None) is None:
        log.info("[no-telegram] HIGH PRIORITY response: %s — %s", cls.category, msg.subject)
        return False
    from src.telegram_bot.cards import response_alert_card

    days_ago = (utcnow() - app.applied_at).days if app and app.applied_at else None
    variant = None
    if app and app.notes and "variant=" in app.notes:
        variant = app.notes.split("variant=", 1)[1].split()[0].strip("|,")
    card = response_alert_card(
        application_id=app.id if app else None,
        company=app.company if app else "(no matching application)",
        role=app.role_title if app else "—",
        days_ago=days_ago,
        from_addr=msg.from_addr, subject=msg.subject,
        body_excerpt=(msg.body_text or "")[:600],
        category=cls.category,
        resume_variant=variant,
    )
    await telegram.send_card(card)
    return True
