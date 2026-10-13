"""Light stealth patches over a Playwright BrowserContext.

This is NOT a fight-detection-to-the-death effort. Our strategy is:
hide the obvious tells (webdriver flag, missing plugins/chrome runtime),
fail soft, and let Tier-3 takeover handle anything that detects us anyway.
"""

from __future__ import annotations

from playwright.async_api import BrowserContext

_INIT_JS = """
(() => {
  // navigator.webdriver
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

  // chrome runtime
  if (!window.chrome) {
    window.chrome = { runtime: {} };
  }

  // plugins
  Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5].map(() => ({})),
  });

  // languages
  Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
})();
"""


async def apply_stealth(ctx: BrowserContext) -> None:
    await ctx.add_init_script(_INIT_JS)
