"""Workable Tier-1 adapter (apply.workable.com)."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from playwright.async_api import Page

from src.ats.base import ApplicationPlan, AskCallback, ATSAdapter, ParsedJob
from src.ats.common import answer_groups, fill_if, infer_company_from_path, text, upload_resume
from src.browser.harness import jitter_sleep

log = logging.getLogger(__name__)


class WorkableAdapter(ATSAdapter):
    name = "workable"
    submit_selectors = (
        "button[data-ui='apply-button']",
        "button[type='submit']:has-text('Submit')",
        "button:has-text('Submit application')",
        "button[type='submit']",
    )

    @classmethod
    def can_handle(cls, url: str, page: Page | None = None) -> bool:
        host = urlparse(url).hostname or ""
        return host == "apply.workable.com" or host.endswith(".workable.com")

    async def parse_job(self, page: Page, url: str) -> ParsedJob:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await jitter_sleep(800, 1500)
        role = await text(page, "h1[data-ui='job-title'], h1") or "Unknown"
        company = (
            await text(page, "h2[data-ui='company-name'], header h2")
            or infer_company_from_path(url)
        )
        description = await text(page, "section[data-ui='job-description'], main")
        return ParsedJob(
            company=company, role=role,
            description_md=description, apply_url=url, requires_account=False,
        )

    async def fill(
        self, page: Page, plan: ApplicationPlan, *, ask: AskCallback | None = None,
    ) -> None:
        for sel in ("a[data-ui='application-button']", "button[data-ui='overview-apply-now']",
                    "a:has-text('Apply for this job')"):
            b = await page.query_selector(sel)
            if b:
                await b.click()
                await jitter_sleep(900, 1500)
                break

        a = plan.answers
        await fill_if(page, "input[name='firstname']", a.get("first_name"))
        await fill_if(page, "input[name='lastname']", a.get("last_name"))
        await fill_if(page, "input[name='email'], input[type='email']", a.get("email"))
        await fill_if(page, "input[name='phone'], input[type='tel']", a.get("phone"))

        await upload_resume(page, plan, "input[type='file'][data-ui='resume'], input[type='file']")

        await answer_groups(
            page, plan,
            group_selector="[data-ui^='QA_'], fieldset, div[class*='question']",
            label_selector="label, legend",
            ask=ask,
        )
