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
from src.ats.common import answer_groups, fill_if, infer_company_from_path, text, upload_resume
from src.browser.harness import jitter_sleep

log = logging.getLogger(__name__)


class LeverAdapter(ATSAdapter):
    name = "lever"
    submit_selectors = (
        "button#btn-submit",
        "button[type='submit']:has-text('Submit')",
        "button[type='submit']",
    )

    @classmethod
    def can_handle(cls, url: str, page: Page | None = None) -> bool:
        return (urlparse(url).hostname or "") == "jobs.lever.co"

    async def parse_job(self, page: Page, url: str) -> ParsedJob:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await jitter_sleep(500, 1000)
        role = await text(page, ".posting-headline h2, h2.posting-name") or "Unknown"
        # Lever doesn't show the company in the DOM — derive it from the URL.
        location = await text(page, ".posting-categories .location, .location")
        description = await text(page, ".section-wrapper, .posting")
        return ParsedJob(
            company=infer_company_from_path(url),
            role=role,
            location=location or None,
            description_md=description,
            apply_url=url,
            requires_account=False,
        )

    async def fill(
        self, page: Page, plan: ApplicationPlan, *, ask: AskCallback | None = None,
    ) -> None:
        if "/apply" not in page.url:
            apply_btn = await page.query_selector("a.postings-btn[href*='/apply'], .apply-button")
            if apply_btn:
                await apply_btn.click()
                await page.wait_for_load_state("domcontentloaded")
                await jitter_sleep(800, 1500)

        a = plan.answers
        full_name = f"{a.get('first_name', '')} {a.get('last_name', '')}".strip()
        await fill_if(page, "input[name='name']", full_name)
        await fill_if(page, "input[name='email']", a.get("email"))
        await fill_if(page, "input[name='phone']", a.get("phone"))
        await fill_if(page, "input[name='urls[LinkedIn]']", a.get("linkedin"))
        await fill_if(page, "input[name='urls[GitHub]']", a.get("github"))
        await fill_if(page, "input[name='urls[Portfolio]'], input[name='urls[Other]']",
                      a.get("portfolio"))

        await upload_resume(page, plan, "input[type='file'][name='resume'], input[type='file']")

        await answer_groups(
            page, plan,
            group_selector=".application-question.custom-question, .custom-question",
            label_selector=".application-label, .text, label",
            ask=ask,
        )
