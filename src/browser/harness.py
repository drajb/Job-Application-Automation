"""Playwright Chromium harness.

- Headed by default (WSLg renders the window on Windows desktop).
- Dedicated persistent profile at chrome-profile-apply/ (NEVER reuse main profile).
- Real residential IP from the host. No proxies.
- Stealth patches via fingerprint.py.
"""

from __future__ import annotations

import asyncio
import logging
import random
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import Page, async_playwright

from src.browser.fingerprint import apply_stealth
from src.config import REPO_ROOT

log = logging.getLogger(__name__)

PROFILE_DIR = REPO_ROOT / "chrome-profile-apply"


@asynccontextmanager
async def browser_session(*, headless: bool = False):
    """Yield (browser_context, page) with stealth applied and a dedicated profile."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/Chicago",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        await apply_stealth(ctx)
        page = await ctx.new_page()
        try:
            yield ctx, page
        finally:
            await ctx.close()


async def jitter_sleep(min_ms: int = 300, max_ms: int = 900) -> None:
    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000.0)


async def reading_pause() -> None:
    """Occasional longer 'reading' pause (2-5s) to look human."""
    await asyncio.sleep(random.uniform(2.0, 5.0))


async def human_type(page: Page, selector: str, text: str) -> None:
    """Type with jitter between keystrokes."""
    await page.click(selector)
    for ch in text:
        await page.keyboard.type(ch)
        await asyncio.sleep(random.uniform(0.02, 0.10))


async def screenshot(page: Page, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(out_path), full_page=True)
    return out_path
