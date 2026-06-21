"""Greenhouse Tier-1 adapter.

Greenhouse public boards expose a fairly predictable DOM:
  - h1.app-title for role
  - .company-name for company
  - #content / .content / .opening for the JD body
  - form fields with id like `job_application_first_name`, `..._last_name`,
    `..._email`, `..._phone`, `..._resume`, plus custom questions.

The adapter is intentionally defensive: it tolerates missing fields and
escalates anything weird via the orchestrator (handoff → Telegram).
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from playwright.async_api import Page

from src.ats.base import ApplicationPlan, ATSAdapter, ParsedJob
from src.browser.harness import human_type, jitter_sleep

log = logging.getLogger(__name__)


class GreenhouseAdapter(ATSAdapter):
    name = "greenhouse"

    @classmethod
    def can_handle(cls, url: str, page: Page | None = None) -> bool:
        host = urlparse(url).netloc
        return "greenhouse.io" in host or "greenhouse" in host

    async def parse_job(self, page: Page, url: str) -> ParsedJob:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await jitter_sleep(500, 1200)

        role = (await _text(page, "h1.app-title, h1")) or "Unknown Role"
        company = (
            await _text(page, ".company-name")
            or await _text(page, "[itemprop='hiringOrganization']")
            or _infer_company_from_url(url)
        )
        description = await _text(page, "#content, .content, .opening, main") or ""

        return ParsedJob(
            company=company.strip(),
            role=role.strip(),
            description_md=description.strip(),
            apply_url=url,
            requires_account=False,  # Greenhouse public boards typically don't
        )

    async def fill(self, page: Page, plan: ApplicationPlan, *, dry_run: bool) -> None:
        # Greenhouse application form is usually on the same page below the JD.
        # Try common selectors. Tolerate missing ones.
        await _fill_if(page, "#first_name, input[autocomplete='given-name']", plan.answers.get("first_name", ""))
        await _fill_if(page, "#last_name, input[autocomplete='family-name']", plan.answers.get("last_name", ""))
        await _fill_if(page, "#email, input[type='email']", plan.answers.get("email", ""))
        await _fill_if(page, "#phone, input[type='tel']", plan.answers.get("phone", ""))

        # Resume upload.
        resume_input = await page.query_selector("input[type='file'][name*='resume'], input[type='file']#resume")
        if resume_input and plan.resume_pdf.exists() and plan.resume_pdf.stat().st_size > 0:
            await resume_input.set_input_files(str(plan.resume_pdf))
            await jitter_sleep(800, 1500)

        # Cover letter (optional text area).
        if plan.cover_letter_md:
            cl = await page.query_selector("textarea[name*='cover'], #cover_letter_text")
            if cl:
                await cl.fill(plan.cover_letter_md)

        # Custom Q&A: walk every label and try to match it to plan.answers / plan.essays.
        # The qa_log feeds plan.answers in advance, so this is best-effort.
        labels = await page.query_selector_all("label")
        for label in labels:
            txt = ((await label.inner_text()) or "").strip()
            if not txt:
                continue
            key = _slug(txt)
            value = plan.answers.get(key) or plan.essays.get(key) or _match_answer(plan, txt)
            if not value:
                continue
            input_id = await label.get_attribute("for")
            if not input_id:
                continue
            try:
                el = await page.query_selector(f"#{input_id}")
                if el is None:
                    continue
                tag = (await el.evaluate("el => el.tagName")).lower()
                if tag == "select":
                    await el.select_option(label=value)
                else:
                    await el.fill(value)
            except Exception as e:
                log.debug("greenhouse custom field skip (%s): %s", txt, e)

        if dry_run:
            log.info("greenhouse: DRY-RUN — skipping final submit click")
            return

        # Click submit only when explicitly told.
        submit = await page.query_selector("button[type='submit'], input[type='submit'], #submit_app")
        if submit:
            await submit.click()
            await jitter_sleep(2000, 4000)


# --- helpers --------------------------------------------------------------


async def _text(page: Page, selector: str) -> str:
    el = await page.query_selector(selector)
    if el is None:
        return ""
    try:
        return (await el.inner_text()).strip()
    except Exception:
        return ""


async def _fill_if(page: Page, selector: str, value: str) -> None:
    if not value:
        return
    el = await page.query_selector(selector)
    if el is None:
        return
    try:
        await human_type(page, selector, value)
    except Exception as e:
        log.debug("greenhouse fill skip (%s): %s", selector, e)


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def _match_answer(plan: ApplicationPlan, label: str) -> str | None:
    lo = label.lower()
    if "linkedin" in lo:
        return plan.answers.get("linkedin")
    if "github" in lo:
        return plan.answers.get("github")
    if "portfolio" in lo or "website" in lo:
        return plan.answers.get("portfolio")
    if "sponsorship" in lo or "visa" in lo or "authorization" in lo:
        return plan.answers.get("sponsorship_response")
    if "salary" in lo or "compensation" in lo:
        return plan.answers.get("salary_expectation")
    if "how did you hear" in lo or "referral source" in lo:
        return plan.answers.get("how_did_you_hear")
    # Fall through to qa_log semantic match.
    try:
        from src.profile.qa_log import lookup
        m = lookup(label)
        if m.decision == "reuse" and m.answer:
            log.info("qa_log reuse score=%.2f for label=%r", m.score, label[:60])
            return m.answer
    except Exception as e:
        log.debug("qa_log lookup skipped: %s", e)
    return None


def _infer_company_from_url(url: str) -> str:
    # boards.greenhouse.io/<company>/jobs/<id>
    p = urlparse(url).path.strip("/").split("/")
    return p[0].replace("-", " ").title() if p else "Unknown"
