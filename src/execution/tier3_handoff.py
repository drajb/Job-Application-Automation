"""Tier-3: human takeover.

The agent has done all the prep (resume tailored, draft answers filled). We
screenshot, post a Telegram card, and KEEP THE BROWSER OPEN until the human
finishes the form in that window and sends /done <app_id> (or /abort), or
until `wait_seconds` passes.

The browser window is headed, so it is already on your desktop (WSLg on
Windows, or a normal window on Linux/macOS).
"""

from __future__ import annotations

import html
import logging
from pathlib import Path

from src.config import DATA_DIR
from src.db.models import Application
from src.db.session import get_session
from src.util.time import utcnow

log = logging.getLogger(__name__)

DEFAULT_WAIT_SECONDS = 30 * 60


async def request_handoff(
    *,
    application_id: int,
    page,  # playwright.async_api.Page | None
    telegram,  # TelegramBot | None
    reason: str,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
) -> str:
    """Snapshot, alert, mark the application as awaiting a human, and wait.

    Returns "done", "aborted" or "timeout" ("timeout" also when there is no
    bot to wait on).
    """
    shot_path: Path | None = None
    if page is not None:
        shot_dir = DATA_DIR / "screenshots"
        shot_dir.mkdir(parents=True, exist_ok=True)
        shot_path = shot_dir / f"handoff_{application_id}.png"
        try:
            await page.screenshot(path=str(shot_path), full_page=True)
        except Exception as e:
            log.warning("screenshot failed: %s", e)
            shot_path = None

    with get_session() as s:
        row = s.get(Application, application_id)
        if row is not None:
            row.status = "handoff"
            row.notes = (row.notes or "") + f" | handoff @ {utcnow().isoformat()} ({reason})"
            if shot_path is not None:
                row.screenshot_path = str(shot_path)
            s.commit()

    live = telegram is not None and getattr(telegram, "_app", None) is not None
    if not live:
        log.warning("handoff for app #%s (%s) — no Telegram; finish it in the browser "
                    "window, then record it with --done %s", application_id, reason, application_id)
        return "timeout"

    window = "The browser window is open — finish the form there" if page is not None else \
        "Open the posting yourself and finish it"
    text = (
        f"🖥 <b>Your turn — app #{application_id}</b>\n\n"
        f"<b>Why:</b> {html.escape(reason)}\n\n"
        f"{window}, then send /done {application_id}. "
        f"Send /abort {application_id} to give up."
    )
    try:
        await telegram.send_html(text)
        if shot_path is not None and shot_path.exists():
            await telegram.send_photo(shot_path, caption=f"app #{application_id} — current state")
    except Exception as e:
        log.warning("handoff notification failed: %s", e)

    if page is None:
        return "timeout"
    return await telegram.wait_for_done(application_id, timeout_seconds=wait_seconds)
