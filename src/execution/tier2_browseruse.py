"""Tier-2: vision-capable browser driving with Gemini 2.5 Flash.

The browser-use library expects a langchain-compatible LLM. We provide a thin
adapter that proxies to our rate-limited GeminiClient so quota accounting works.

Confidence < 0.7 → pause via Telegram handoff. This is wired in the orchestrator,
not inside this module.
"""

from __future__ import annotations

import logging

from src.config import Settings
from src.llm.client import GeminiClient

log = logging.getLogger(__name__)


async def run_tier2(
    *,
    url: str,
    task: str,
    settings: Settings,
    client: GeminiClient | None = None,
    max_steps: int = 40,
) -> dict:
    """Drive a browser through `task` until done or max_steps. Return result dict.

    This is a lightweight implementation that delegates DOM-level actions
    to Playwright. We do NOT pull in browser-use itself for the initial cut —
    its API surface changes quickly, and our use case here is narrow (parse a JD
    + apply, not general web browsing).

    The plan:
      1. Take a stripped DOM snapshot.
      2. Ask Gemini "what's the next action?" with a fixed action grammar.
      3. Execute the action. Repeat.
    """
    if client is None:
        client = GeminiClient(settings)

    from src.browser.harness import browser_session
    history: list[dict] = []
    async with browser_session(headless=False) as (_ctx, page):
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        for step in range(max_steps):
            snapshot = await _snapshot(page)
            action = await _next_action(client, task, snapshot, history)
            history.append(action)
            log.info("tier2 step %d action=%s confidence=%.2f",
                     step, action.get("type"), action.get("confidence", 0))
            if action.get("type") == "done":
                return {"status": "done", "history": history, "snapshot": snapshot}
            if action.get("confidence", 1.0) < 0.7:
                return {
                    "status": "low_confidence", "history": history,
                    "snapshot": snapshot, "action": action,
                }
            await _execute(page, action)
        return {"status": "max_steps_reached", "history": history}


async def _snapshot(page) -> str:
    """Return a compact text representation of the visible page."""
    title = await page.title()
    url = page.url
    body = await page.evaluate("() => document.body ? document.body.innerText.slice(0, 6000) : ''")
    return f"URL: {url}\nTitle: {title}\n---\n{body}"


async def _next_action(client: GeminiClient, task: str, snapshot: str, history: list[dict]) -> dict:
    """Ask Gemini for the next action in a constrained JSON grammar."""
    history_str = "\n".join(f"- {h}" for h in history[-6:])
    prompt = f"""You are driving a web browser to complete this task:

TASK: {task}

Recent actions (most recent last):
{history_str or "(none)"}

Current page snapshot:
{snapshot[:4000]}

Pick ONE next action. Return JSON only, no commentary, matching one of:

  {{"type":"goto","url":"<url>","confidence":0.0-1.0}}
  {{"type":"click","selector":"<css>","confidence":0.0-1.0}}
  {{"type":"fill","selector":"<css>","value":"<text>","confidence":0.0-1.0}}
  {{"type":"upload","selector":"<css>","path":"<absolute_path>","confidence":0.0-1.0}}
  {{"type":"scroll","y":<pixels>,"confidence":0.0-1.0}}
  {{"type":"wait","seconds":<n>,"confidence":0.0-1.0}}
  {{"type":"done","summary":"<one line>","confidence":1.0}}

Use confidence < 0.7 if you're unsure — that triggers human handoff.
"""
    out = await client.generate(prompt, temperature=0.1, json_mode=True, max_output_tokens=512)
    try:
        import json
        return json.loads(out)
    except Exception:
        log.warning("tier2: non-JSON response, treating as low confidence")
        return {"type": "wait", "seconds": 1, "confidence": 0.0}


async def _execute(page, action: dict) -> None:
    t = action.get("type")
    if t == "goto":
        await page.goto(action["url"], wait_until="domcontentloaded", timeout=30_000)
    elif t == "click":
        await page.click(action["selector"], timeout=10_000)
    elif t == "fill":
        await page.fill(action["selector"], action["value"], timeout=10_000)
    elif t == "upload":
        el = await page.query_selector(action["selector"])
        if el is not None:
            await el.set_input_files(action["path"])
    elif t == "scroll":
        await page.evaluate(f"window.scrollBy(0, {int(action.get('y', 500))})")
    elif t == "wait":
        import asyncio
        await asyncio.sleep(float(action.get("seconds", 1)))
    else:
        log.warning("tier2: unknown action type %s", t)
