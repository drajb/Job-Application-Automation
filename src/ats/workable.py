"""Workable Tier-1 adapter (apply.workable.com)."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from playwright.async_api import Page

from src.ats.base import ApplicationPlan, AskCallback, ATSAdapter, ParsedJob
from src.browser.harness import jitter_sleep

log = logging.getLogger(__name__)


class WorkableAdapter(ATSAdapter):
    name = "workable"

    @classmethod
    def can_handle(cls, url: str, page: Page | None = None) -> bool:
        return "workable.com" in urlparse(url).netloc

    async def parse_job(self, page: Page, url: str) -> ParsedJob:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await jitter_sleep(800, 1500)
        role = await _t(page, "h1[data-ui='job-title'], h1") or "Unknown"
        company = await _t(page, "h2[data-ui='company-name'], header h2") or _company_from_url(url)
        description = await _t(page, "section[data-ui='job-description'], main") or ""
        return ParsedJob(
            company=company, role=role,
            description_md=description, apply_url=url, requires_account=False,
        )

    async def fill(
        self, page: Page, plan: ApplicationPlan, *, dry_run: bool, ask: AskCallback | None = None,
    ) -> None:
        for sel in ("a[data-ui='application-button']", "button:has-text('Apply')"):
            b = await page.query_selector(sel)
            if b:
                await b.click()
                await jitter_sleep(900, 1500)
                break

        await _safe_fill(page, "input[name='firstname']", plan.answers.get("first_name", ""))
        await _safe_fill(page, "input[name='lastname']", plan.answers.get("last_name", ""))
        await _safe_fill(page, "input[type='email']", plan.answers.get("email", ""))
        await _safe_fill(page, "input[name='phone']", plan.answers.get("phone", ""))

        f = await page.query_selector("input[type='file']")
        if f and plan.resume_pdf.exists() and plan.resume_pdf.stat().st_size > 0:
            await f.set_input_files(str(plan.resume_pdf))
            await jitter_sleep(800, 1500)

        if dry_run:
            log.info("workable: DRY-RUN — skipping submit")
            return
        for sel in ("button[type='submit']:has-text('Submit')",
                    "button:has-text('Submit application')"):
            b = await page.query_selector(sel)
            if b:
                await b.click()
                await jitter_sleep(2000, 4000)
                break


async def _t(page, sel):
    el = await page.query_selector(sel)
    return ((await el.inner_text()).strip() if el else "")


async def _safe_fill(page, sel, value):
    if not value:
        return
    el = await page.query_selector(sel)
    if el:
        import contextlib
        with contextlib.suppress(Exception):
            await el.fill(value)


def _company_from_url(url):
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0].replace("-", " ").title() if parts else "Unknown"
