"""Ashby Tier-1 adapter.

Ashby hosts at jobs.ashbyhq.com/<company>/<job-id>. The app uses React with
hashed class names, so selectors are attribute-substring / aria based.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from playwright.async_api import Page

from src.ats.base import ApplicationPlan, AskCallback, ATSAdapter, ParsedJob
from src.ats.common import answer_groups, fill_if, infer_company_from_path, text, upload_resume
from src.browser.harness import jitter_sleep

log = logging.getLogger(__name__)


class AshbyAdapter(ATSAdapter):
    name = "ashby"
    submit_selectors = (
        "button[class*='submit']",
        "button:has-text('Submit Application')",
        "button[type='submit']",
    )

    @classmethod
    def can_handle(cls, url: str, page: Page | None = None) -> bool:
        return (urlparse(url).hostname or "") == "jobs.ashbyhq.com"

    async def parse_job(self, page: Page, url: str) -> ParsedJob:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await jitter_sleep(800, 1500)
        role = await text(page, "h1") or "Unknown"
        company = infer_company_from_path(url)
        description = await text(
            page, "[class*='_descriptionText_'], .ashby-job-description, main",
        )
        return ParsedJob(
            company=company, role=role,
            description_md=description, apply_url=url,
            requires_account=False,
        )

    async def fill(
        self, page: Page, plan: ApplicationPlan, *, ask: AskCallback | None = None,
    ) -> None:
        # The application form lives on the /application tab.
        if not page.url.rstrip("/").endswith("/application"):
            for sel in ("a[href$='/application']", "button:has-text('Apply for this Job')",
                        "a:has-text('Apply for this Job')"):
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    await jitter_sleep(1000, 2000)
                    break

        a = plan.answers
        full_name = f"{a.get('first_name', '')} {a.get('last_name', '')}".strip()
        await fill_if(page, "input[name='_systemfield_name'], input[name*='name' i]", full_name)
        await fill_if(page, "input[name='_systemfield_email'], input[type='email']", a.get("email"))
        await fill_if(page, "input[name*='phone' i], input[type='tel']", a.get("phone"))

        await upload_resume(
            page, plan, "input[type='file'][id*='resume' i], input[type='file']",
        )

        await answer_groups(
            page, plan,
            group_selector="[class*='_fieldEntry_'], fieldset",
            label_selector="label, legend",
            ask=ask,
        )
