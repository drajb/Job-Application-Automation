"""LinkedIn Easy Apply — TIER-3 ONLY. NEVER AUTOMATED.

Per docs/SPEC.md Hard Rules: LinkedIn is handled only via Tier-3 manual
takeover. This module:
  1. Opens the JD URL in headed Chrome with the existing session.
  2. Posts a Telegram handoff card.
  3. EXITS. The user finishes the Easy Apply flow by hand.

There is no automatic clicking of Easy Apply, no auto-fill, no auto-submit.
"""

from __future__ import annotations

import logging

from playwright.async_api import async_playwright

from src.config import Settings
from src.linkedin.session import has_session, session_path

log = logging.getLogger(__name__)


async def open_for_takeover(
    *,
    url: str,
    settings: Settings,
    telegram=None,
) -> None:
    if not has_session():
        log.error(
            "no LinkedIn session at %s — see docs/LINKEDIN.md to save one",
            session_path(),
        )
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # headed for the user
        ctx = await browser.new_context(storage_state=str(session_path()))
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        log.info("LinkedIn job opened. WAITING FOR HUMAN. Use /done when finished.")
        if telegram is not None and telegram.configured() and telegram._app is not None:
            await telegram._app.bot.send_message(
                chat_id=telegram.settings.telegram_chat_id,
                text=(
                    f"🖥 LinkedIn JD opened: {url}\n\n"
                    f"This is Tier-3. Finish the Easy Apply manually, then /done."
                ),
            )

        # Keep the browser open. The orchestrator typically waits for /done
        # and then closes the context. For a one-shot CLI run, sleep forever.
        try:
            import asyncio
            await asyncio.Event().wait()
        finally:
            await ctx.close()
            await browser.close()
