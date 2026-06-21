"""SmartRecruiters Tier-1 adapter (jobs.smartrecruiters.com)."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from playwright.async_api import Page

from src.ats.base import ApplicationPlan, ATSAdapter, ParsedJob
from src.browser.harness import jitter_sleep

log = logging.getLogger(__name__)


class SmartRecruitersAdapter(ATSAdapter):
    name = "smartrecruiters"

    @classmethod
    def can_handle(cls, url: str, page: Page | None = None) -> bool:
        return "smartrecruiters.com" in urlparse(url).netloc

    async def parse_job(self, page: Page, url: str) -> ParsedJob:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await jitter_sleep(800, 1500)
        role = await _t(page, "h1") or "Unknown"
        company = await _t(page, "[data-test='company-name'], a[href*='/companies/']") or _co(url)
        description = await _t(page, "section.job-sections, main") or ""
        return ParsedJob(
            company=company, role=role,
            description_md=description, apply_url=url, requires_account=True,
        )

    async def fill(self, page: Page, plan: ApplicationPlan, *, dry_run: bool) -> None:
        for sel in ("button:has-text('I'm interested')",
                    "a[data-track='apply-button']", "button:has-text('Apply')"):
            b = await page.query_selector(sel)
            if b:
                await b.click()
                await jitter_sleep(900, 1600)
                break

        await _f(page, "input[name='firstName']", plan.answers.get("first_name", ""))
        await _f(page, "input[name='lastName']", plan.answers.get("last_name", ""))
        await _f(page, "input[type='email']", plan.answers.get("email", ""))
        await _f(page, "input[name='phoneNumber']", plan.answers.get("phone", ""))

        fi = await page.query_selector("input[type='file']")
        if fi and plan.resume_pdf.exists() and plan.resume_pdf.stat().st_size > 0:
            await fi.set_input_files(str(plan.resume_pdf))
            await jitter_sleep(800, 1500)

        if dry_run:
            log.info("smartrecruiters: DRY-RUN — skipping submit")
            return
        for sel in ("button:has-text('Submit')", "button[type='submit']"):
            b = await page.query_selector(sel)
            if b:
                await b.click()
                await jitter_sleep(2000, 4000)
                break


async def _t(page, sel):
    el = await page.query_selector(sel)
    return ((await el.inner_text()).strip() if el else "")


async def _f(page, sel, val):
    if not val:
        return
    el = await page.query_selector(sel)
    if el:
        import contextlib
        with contextlib.suppress(Exception):
            await el.fill(val)


def _co(url):
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0].replace("-", " ").title() if parts else "Unknown"
