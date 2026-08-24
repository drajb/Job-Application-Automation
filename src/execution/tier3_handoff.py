"""Tier-3: human takeover.

The agent has done all the prep (resume tailored, account ready, draft answers).
We pause, post a Telegram card with a screenshot, and wait for the user to drive
the Chrome window (already on the Windows desktop via WSLg) to completion.

User confirms with /done <app_id>.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.config import DATA_DIR
from src.db.models import Application
from src.db.session import get_session
from src.util.time import utcnow

log = logging.getLogger(__name__)


async def request_handoff(
    *,
    application_id: int,
    page,  # playwright.async_api.Page
    telegram,  # TelegramBot
    reason: str,
) -> Path:
    """Snapshot, alert, mark application as awaiting human."""
    shot_dir = DATA_DIR / "screenshots"
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shot_dir / f"handoff_{application_id}.png"
    try:
        await page.screenshot(path=str(shot_path), full_page=True)
    except Exception as e:
        log.warning("screenshot failed: %s", e)

    with get_session() as s:
        row = s.get(Application, application_id)
        if row is not None:
            row.status = "handoff"
            row.notes = (row.notes or "") + f" | handoff @ {utcnow().isoformat()} ({reason})"
            row.screenshot_path = str(shot_path)
            s.commit()

    if telegram is not None and telegram.configured() and telegram._app is not None:
        from telegram.constants import ParseMode
        await telegram._app.bot.send_message(
            chat_id=telegram.settings.telegram_chat_id,
            text=(
                f"🖥 *Handoff requested — app #{application_id}*\n\n"
                f"Reason: {reason}\n\n"
                f"Chrome window is open. Drive it to completion, then /done {application_id}."
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        try:
            with shot_path.open("rb") as fh:
                await telegram._app.bot.send_photo(
                    chat_id=telegram.settings.telegram_chat_id,
                    photo=fh,
                )
        except Exception as e:
            log.warning("could not send screenshot: %s", e)
    return shot_path
