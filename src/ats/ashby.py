"""Ashby Tier-1 adapter.

Ashby hosts at jobs.ashbyhq.com/<company>/<job-id>. The app uses React, so
selectors are mostly aria-label / data-* based.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from playwright.async_api import Page

from src.ats.base import ApplicationPlan, AskCallback, ATSAdapter, ParsedJob
from src.browser.harness import jitter_sleep

log = logging.getLogger(__name__)


class AshbyAdapter(ATSAdapter):
    name = "ashby"

    @classmethod
    def can_handle(cls, url: str, page: Page | None = None) -> bool:
        return "jobs.ashbyhq.com" in urlparse(url).netloc

    async def parse_job(self, page: Page, url: str) -> ParsedJob:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await jitter_sleep(800, 1500)
        role = await _text(page, "h1") or "Unknown"
        company = await _text(page, "header a, .companyName") or _infer_company(url)
        description = await _text(page, "._descriptionText_*, .ashby-job-description, main") or ""
        return ParsedJob(
            company=company, role=role,
            description_md=description, apply_url=url,
            requires_account=False,
        )

    async def fill(
        self, page: Page, plan: ApplicationPlan, *, dry_run: bool, ask: AskCallback | None = None,
    ) -> None:
        # The "Apply" button opens a panel/modal.
        for sel in ("button:has-text('Apply')", "a:has-text('Apply')"):
            btn = await page.query_selector(sel)
            if btn:
                await btn.click()
                await jitter_sleep(1000, 2000)
                break

        await _fill_input(page, "name", _fullname(plan))
        await _fill_input(page, "email", plan.answers.get("email", ""))
        await _fill_input(page, "phone", plan.answers.get("phone", ""))

        f = await page.query_selector("input[type='file']")
        if f and plan.resume_pdf.exists() and plan.resume_pdf.stat().st_size > 0:
            await f.set_input_files(str(plan.resume_pdf))
            await jitter_sleep(800, 1500)

        # Custom questions
        groups = await page.query_selector_all("[class*='Field_'], fieldset")
        for g in groups:
            label_el = await g.query_selector("label, legend, [class*='label_']")
            if not label_el:
                continue
            label = ((await label_el.inner_text()) or "").strip()
            answer = _match(plan, label)
            if not answer:
                continue
            try:
                if (ta := await g.query_selector("textarea")):
                    await ta.fill(answer)
                elif (sel := await g.query_selector("select")):
                    await sel.select_option(label=answer)
                elif (inp := await g.query_selector("input[type='text'], input[type='email']")):
                    await inp.fill(answer)
            except Exception as e:
                log.debug("ashby skip: %s", e)

        if dry_run:
            log.info("ashby: DRY-RUN — skipping submit")
            return
        for sel in ("button[type='submit']", "button:has-text('Submit')"):
            b = await page.query_selector(sel)
            if b:
                await b.click()
                await jitter_sleep(2000, 4000)
                break


async def _text(page, selector):
    el = await page.query_selector(selector)
    return ((await el.inner_text()).strip() if el else "")


async def _fill_input(page, name_substr, value):
    if not value:
        return
    for sel in (
        f"input[name*='{name_substr}']",
        f"input[id*='{name_substr}']",
        f"input[placeholder*='{name_substr}' i]",
    ):
        el = await page.query_selector(sel)
        if el is not None:
            try:
                await el.fill(value)
                return
            except Exception:
                continue


def _infer_company(url: str) -> str:
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0].replace("-", " ").title() if parts else "Unknown"


def _fullname(plan):
    return f"{plan.answers.get('first_name','')} {plan.answers.get('last_name','')}".strip()


def _match(plan, label):
    lo = label.lower()
    if any(k in lo for k in ("sponsorship", "visa", "authorization")):
        return plan.answers.get("sponsorship_response")
    if "salary" in lo:
        return plan.answers.get("salary_expectation")
    if "linkedin" in lo:
        return plan.answers.get("linkedin")
    if "github" in lo:
        return plan.answers.get("github")
    if "portfolio" in lo or "website" in lo:
        return plan.answers.get("portfolio")
    return None
