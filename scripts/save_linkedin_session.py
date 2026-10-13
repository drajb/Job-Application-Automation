"""Headed Playwright login to LinkedIn → save storage_state.json.

Usage:
    python -m scripts.save_linkedin_session

A Chromium window opens. Log in normally (2FA, captcha, whatever). When you
see your LinkedIn feed, return to this terminal and press Enter. The script
writes storage state to `secrets/linkedin/storage_state.json` (or wherever
`LINKEDIN_SESSION_PATH` points) and exits.

The agent NEVER does this for you — login flows have too many edge cases
(2FA, security challenges, captchas) and getting it wrong burns your account.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from src.linkedin.session import SESSION_PATH


async def main() -> int:
    out = Path(SESSION_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto("https://www.linkedin.com/login")

        print("\n" + "=" * 60)
        print("Log in to LinkedIn in the browser window that just opened.")
        print("Complete any 2FA / captcha challenges.")
        print("When you can see your LinkedIn feed, come back here.")
        print("=" * 60)
        input("Press Enter to save the session and exit... ")

        await ctx.storage_state(path=str(out))
        await ctx.close()
        await browser.close()
        with contextlib.suppress(PermissionError, OSError):
            out.chmod(0o600)

    print(f"\nSaved: {out}")
    print("Re-run this script every few months — li_at cookies age out.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
