"""Top-level on_message handler. Glues correlator + classifier + matcher.

Wired into imap_idle.listen(settings, on_message=handle).
"""

from __future__ import annotations

import logging

from src.config import Settings
from src.db.models import ResponseLog
from src.db.session import get_session
from src.email_monitor.classifier import HIGH_PRIORITY, classify
from src.email_monitor.imap_idle import IncomingEmail
from src.email_monitor.matcher import match
from src.email_monitor.signup_correlator import match_and_fulfill
from src.util.time import utcnow

log = logging.getLogger(__name__)


async def make_handler(settings: Settings, telegram=None):
    """Return an async on_message(IncomingEmail) callback."""

    async def handle(msg: IncomingEmail) -> None:
        # 1) Try to fulfill a signup expectation first (fast, no LLM cost).
        if (eid := match_and_fulfill(msg)) is not None:
            log.info("email handled as signup fulfillment (#%s)", eid)
            return

        # 2) Classify as response.
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
            s.commit()
            row_id = row.id

        # 4) Notify if high priority.
        if cls.category in HIGH_PRIORITY:
            await _alert(telegram, app, msg, cls)
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


async def _alert(telegram, app, msg: IncomingEmail, cls) -> None:
    if telegram is None or not telegram.configured() or telegram._app is None:
        log.info("[no-telegram] HIGH PRIORITY response: %s — %s", cls.category, msg.subject)
        return
    from src.telegram_bot.cards import response_alert_card

    company = app.company if app else "(unmatched)"
    role = app.role_title if app else "(unmatched)"
    days_ago = 0
    if app and app.applied_at:
        days_ago = (utcnow() - app.applied_at).days
    card = response_alert_card(
        application_id=app.id if app else 0,
        company=company, role=role, days_ago=days_ago,
        from_addr=msg.from_addr, subject=msg.subject,
        body_excerpt=(msg.body_text or "")[:600],
        category=cls.category,
    )
    await telegram.send_card(card)
