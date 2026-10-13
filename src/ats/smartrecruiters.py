"""SmartRecruiters Tier-1 adapter (jobs.smartrecruiters.com)."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from playwright.async_api import Page

from src.ats.base import ApplicationPlan, AskCallback, ATSAdapter, ParsedJob
from src.ats.common import answer_groups, fill_if, infer_company_from_path, text, upload_resume
from src.browser.harness import jitter_sleep

log = logging.getLogger(__name__)


class SmartRecruitersAdapter(ATSAdapter):
    name = "smartrecruiters"
    submit_selectors = (
        "button[data-test='footer-submit']",
        "button:has-text('Submit')",
        "button[type='submit']",
    )

    @classmethod
    def can_handle(cls, url: str, page: Page | None = None) -> bool:
        host = urlparse(url).hostname or ""
        return host == "smartrecruiters.com" or host.endswith(".smartrecruiters.com")

    async def parse_job(self, page: Page, url: str) -> ParsedJob:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await jitter_sleep(800, 1500)
        role = await text(page, "h1") or "Unknown"
        company = (
            await text(page, "[data-test='company-name'], a[href*='/companies/']")
            or infer_company_from_path(url)
        )
        description = await text(page, "section.job-sections, main")
        # The public "I'm interested" flow is a guest application — no account.
        return ParsedJob(
            company=company, role=role,
            description_md=description, apply_url=url, requires_account=False,
        )

    async def fill(
        self, page: Page, plan: ApplicationPlan, *, ask: AskCallback | None = None,
    ) -> None:
        for sel in ('button:has-text("I\'m interested")',
                    "a[data-track='apply-button']", "button:has-text('Apply')"):
            b = await page.query_selector(sel)
            if b:
                await b.click()
                await jitter_sleep(900, 1600)
                break

        a = plan.answers
        await fill_if(page, "input[name='firstName']", a.get("first_name"))
        await fill_if(page, "input[name='lastName']", a.get("last_name"))
        await fill_if(page, "input[name='email'], input[type='email']", a.get("email"))
        await fill_if(page, "input[name='phoneNumber'], input[type='tel']", a.get("phone"))

        await upload_resume(page, plan, "input[type='file']")

        await answer_groups(
            page, plan,
            group_selector="spl-form-field, fieldset, .question",
            label_selector="label, legend",
            ask=ask,
        )
