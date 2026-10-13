"""DOM helpers shared by every Tier-1 adapter.

Adapters only know their ATS's selectors; the mechanics of answering a
question group, picking a <select> option, uploading the resume, clicking
Submit and confirming it went through live here, once.
"""

from __future__ import annotations

import logging
import re

from playwright.async_api import ElementHandle, Page

from src.ats.base import ApplicationPlan, AskCallback, SubmitError
from src.ats.fields import answer_for, pick_option
from src.browser.harness import human_type, jitter_sleep

log = logging.getLogger(__name__)

# Text that shows up on ATS confirmation pages after a successful submit.
_CONFIRM_RE = re.compile(
    r"thank you for (?:applying|your (?:application|interest))|application (?:has been )?"
    r"(?:received|submitted)|we(?:'ve| have) received your application|"
    r"successfully (?:applied|submitted)|your application was sent",
    re.I,
)


async def text(page: Page, selector: str) -> str:
    """inner_text of the first match, '' on no match or any selector error."""
    try:
        el = await page.query_selector(selector)
        return (await el.inner_text()).strip() if el else ""
    except Exception as e:
        log.debug("text(%s) failed: %s", selector, e)
        return ""


async def fill_if(page: Page, selector: str, value: str | None) -> bool:
    """Type `value` into the first match of `selector`. True if filled."""
    if not value:
        return False
    try:
        el = await page.query_selector(selector)
    except Exception as e:
        log.debug("bad selector %s: %s", selector, e)
        return False
    if el is None:
        return False
    try:
        await human_type(page, selector, value)
    except Exception:
        try:
            await el.fill(value)
        except Exception as e:
            log.debug("fill skip %s: %s", selector, e)
            return False
    return True


async def upload_resume(page: Page, plan: ApplicationPlan, selector: str) -> bool:
    if not plan.resume_pdf.exists() or plan.resume_pdf.stat().st_size == 0:
        log.warning("resume PDF missing/empty (%s) — not uploading", plan.resume_pdf)
        return False
    try:
        f = await page.query_selector(selector)
    except Exception as e:
        log.debug("bad selector %s: %s", selector, e)
        return False
    if f is None:
        return False
    await f.set_input_files(str(plan.resume_pdf))
    await jitter_sleep(800, 1500)
    return True


async def _input_kind(el: ElementHandle) -> str:
    tag = (await el.evaluate("e => e.tagName")).lower()
    if tag in ("select", "textarea"):
        return tag
    typ = ((await el.get_attribute("type")) or "text").lower()
    return typ


async def fill_element(el: ElementHandle, value: str) -> bool:
    """Fill a text input / textarea / select. Returns True if a value was set."""
    kind = await _input_kind(el)
    if kind in ("file", "hidden", "submit", "button", "radio", "checkbox"):
        return False
    if kind == "select":
        options = await el.evaluate("s => Array.from(s.options).map(o => o.label || o.text)")
        choice = pick_option(options, value)
        if choice is None:
            log.info("no <select> option matches %r (options: %s)", value[:40], options[:8])
            return False
        await el.select_option(label=choice)
        return True
    current = await el.input_value() if kind != "textarea" else await el.evaluate("e => e.value")
    if current and current.strip():
        return False  # already answered (autofill / earlier pass) — don't clobber
    await el.fill(value)
    return True


async def _fill_radio_group(group: ElementHandle, value: str) -> bool:
    radios = await group.query_selector_all("input[type='radio']")
    if not radios:
        return False
    labels = []
    for r in radios:
        rid = await r.get_attribute("id")
        lab = ""
        if rid:
            le = await group.query_selector(f"label[for='{rid}']")
            lab = (await le.inner_text()).strip() if le else ""
        if not lab:
            lab = (await r.get_attribute("value")) or ""
        labels.append(lab)
    choice = pick_option(labels, value)
    if choice is None:
        return False
    await radios[labels.index(choice)].check()
    return True


async def answer_groups(
    page: Page,
    plan: ApplicationPlan,
    *,
    group_selector: str,
    label_selector: str,
    ask: AskCallback | None,
) -> int:
    """Answer every question group on the page. Returns how many were filled.

    For each group: read its label → deterministic profile answer → essay →
    `ask` (learned qa_log, then a human over Telegram). Groups whose only
    input is a file upload, or that are already filled, are skipped, so we
    never ask a human about "Resume/CV" or about radio option labels.
    """
    try:
        groups = await page.query_selector_all(group_selector)
    except Exception as e:
        log.warning("bad group selector %s: %s", group_selector, e)
        return 0
    filled = 0
    for g in groups:
        label_el = await g.query_selector(label_selector)
        if label_el is None:
            continue
        label = re.sub(r"\s*\*\s*$", "", ((await label_el.inner_text()) or "").strip())
        if not label:
            continue
        target = await g.query_selector("textarea, select, input:not([type='hidden'])")
        if target is None:
            continue
        kind = await _input_kind(target)
        if kind in ("file", "submit", "button", "checkbox"):
            continue
        if kind not in ("radio", "select"):
            cur = await target.evaluate("e => e.value || ''")
            if cur.strip():
                continue

        value = answer_for(plan, label) or plan.essays.get(label)
        if not value and ask is not None:
            value = await ask(label)
        if not value:
            continue
        try:
            ok = await (_fill_radio_group(g, value) if kind == "radio" else fill_element(target, value))
        except Exception as e:
            log.debug("question skip (%s): %s", label[:60], e)
            ok = False
        filled += int(ok)
    return filled


async def click_submit(page: Page, selectors: tuple[str, ...]) -> None:
    """Click the first visible submit control or raise SubmitError."""
    for sel in selectors:
        try:
            btn = await page.query_selector(sel)
        except Exception:
            continue
        if btn is not None and await btn.is_visible():
            await btn.click()
            return
    raise SubmitError(f"no visible submit button (tried {', '.join(selectors)})")


async def wait_for_confirmation(page: Page, before_url: str, *, timeout_s: float = 20.0) -> bool:
    """True once the page shows a confirmation message or navigates to a
    confirmation URL. False if neither happens within `timeout_s`."""
    deadline = timeout_s * 1000
    step = 1000
    waited = 0
    while waited <= deadline:
        try:
            body = await page.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception:
            body = ""
        if _CONFIRM_RE.search(body or ""):
            return True
        url = page.url
        if url != before_url and re.search(r"confirm|thank|success|submitted", url, re.I):
            return True
        await page.wait_for_timeout(step)
        waited += step
    return False


def infer_company_from_path(url: str) -> str:
    """`https://jobs.lever.co/acme-inc/123` → 'Acme Inc'."""
    from urllib.parse import urlparse

    parts = [p for p in urlparse(url).path.split("/") if p]
    return parts[0].replace("-", " ").title() if parts else "Unknown"
