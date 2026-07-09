"""Lever Tier-1 adapter.

Lever job pages are at jobs.lever.co/<company>/<job-id>. The DOM is fairly
stable:
  .posting-headline h2          → role
  .posting-categories .location → location
  .section-wrapper              → JD body
  .application-form             → form

The "Apply for this job" button leads to a dedicated /apply page where the form
lives. Resume upload via input[type=file].
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from playwright.async_api import Page

from src.ats.base import ApplicationPlan, AskCallback, ATSAdapter, ParsedJob
from src.browser.harness import human_type, jitter_sleep

log = logging.getLogger(__name__)


class LeverAdapter(ATSAdapter):
    name = "lever"

    @classmethod
    def can_handle(cls, url: str, page: Page | None = None) -> bool:
        return "jobs.lever.co" in urlparse(url).netloc

    async def parse_job(self, page: Page, url: str) -> ParsedJob:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await jitter_sleep(500, 1000)
        role = await _text(page, ".posting-headline h2, h2.posting-name") or "Unknown"
        # Lever doesn't show company in DOM — derive from URL.
        company = _infer_company(url)
        location = await _text(page, ".posting-categories .location, .location")
        description = await _text(page, ".section-wrapper, .posting") or ""
        return ParsedJob(
            company=company,
            role=role,
            location=location or None,
            description_md=description,
            apply_url=url,
            requires_account=False,
        )

    async def fill(
        self, page: Page, plan: ApplicationPlan, *, dry_run: bool, ask: AskCallback | None = None,
    ) -> None:
        # Navigate to /apply if not already there.
        if "/apply" not in page.url:
            apply_btn = await page.query_selector("a.postings-btn[href*='/apply'], .apply-button")
            if apply_btn:
                await apply_btn.click()
                await jitter_sleep(800, 1500)

        await _fill_if(page, "input[name='name']", _fullname(plan))
        await _fill_if(page, "input[name='email']", plan.answers.get("email", ""))
        await _fill_if(page, "input[name='phone']", plan.answers.get("phone", ""))
        await _fill_if(page, "input[name='urls[LinkedIn]']", plan.answers.get("linkedin", ""))
        await _fill_if(page, "input[name='urls[GitHub]']", plan.answers.get("github", ""))
        await _fill_if(page, "input[name='urls[Portfolio]'], input[name='urls[Other]']",
                       plan.answers.get("portfolio", ""))

        # Resume
        f = await page.query_selector("input[type='file'][name='resume']")
        if f and plan.resume_pdf.exists() and plan.resume_pdf.stat().st_size > 0:
            await f.set_input_files(str(plan.resume_pdf))
            await jitter_sleep(800, 1500)

        # Custom questions: walk .application-question groups.
        groups = await page.query_selector_all(".application-question, .field")
        for g in groups:
            label_el = await g.query_selector("label, .application-label, .question-label")
            if label_el is None:
                continue
            label = ((await label_el.inner_text()) or "").strip()
            if not label:
                continue
            answer = _match(plan, label)
            if not answer:
                continue
            ta = await g.query_selector("textarea")
            inp = await g.query_selector("input[type='text'], input[type='email'], input[type='tel']")
            sel = await g.query_selector("select")
            try:
                if ta:
                    await ta.fill(answer)
                elif sel:
                    await sel.select_option(label=answer)
                elif inp:
                    await inp.fill(answer)
            except Exception as e:
                log.debug("lever custom field skip (%s): %s", label[:60], e)

        if dry_run:
            log.info("lever: DRY-RUN — skipping submit")
            return
        submit = await page.query_selector("button[type='submit'], input[type='submit']")
        if submit:
            await submit.click()
            await jitter_sleep(2000, 4000)


# --- shared helpers --------------------------------------------------------


async def _text(page, selector):
    el = await page.query_selector(selector)
    if el is None:
        return ""
    try:
        return (await el.inner_text()).strip()
    except Exception:
        return ""


async def _fill_if(page, selector, value):
    if not value:
        return
    el = await page.query_selector(selector)
    if el is None:
        return
    try:
        await human_type(page, selector, value)
    except Exception:
        try:
            await el.fill(value)
        except Exception as e:
            log.debug("fill skip %s: %s", selector, e)


def _infer_company(url: str) -> str:
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0].replace("-", " ").title() if parts else "Unknown"


def _fullname(plan: ApplicationPlan) -> str:
    fn = plan.answers.get("first_name", "")
    ln = plan.answers.get("last_name", "")
    return f"{fn} {ln}".strip()


def _match(plan: ApplicationPlan, label: str) -> str | None:
    lo = label.lower()
    if any(k in lo for k in ("sponsorship", "visa", "authorization")):
        return plan.answers.get("sponsorship_response")
    if "salary" in lo or "compensation" in lo:
        return plan.answers.get("salary_expectation")
    if "how did you hear" in lo:
        return plan.answers.get("how_did_you_hear")
    return None
