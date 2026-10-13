"""Greenhouse Tier-1 adapter.

Greenhouse public boards expose a fairly predictable DOM:
  - h1.app-title / h1 for role
  - .company-name for company
  - #content / .content / .opening for the JD body
  - form fields #first_name, #last_name, #email, #phone, a resume file input,
    plus custom questions wrapped in .field (classic) or .text-input-wrapper /
    .select (new job-boards.greenhouse.io UI).

The adapter is intentionally defensive: it tolerates missing fields and
escalates anything weird via the orchestrator (handoff → Telegram).
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from playwright.async_api import Page

from src.ats.base import ApplicationPlan, AskCallback, ATSAdapter, ParsedJob
from src.ats.common import answer_groups, fill_if, infer_company_from_path, text, upload_resume
from src.browser.harness import jitter_sleep

log = logging.getLogger(__name__)


class GreenhouseAdapter(ATSAdapter):
    name = "greenhouse"
    submit_selectors = (
        "#submit_app",
        "button[type='submit']:has-text('Submit')",
        "button[type='submit']",
        "input[type='submit']",
    )

    @classmethod
    def can_handle(cls, url: str, page: Page | None = None) -> bool:
        host = urlparse(url).hostname or ""
        return host == "greenhouse.io" or host.endswith(".greenhouse.io")

    async def parse_job(self, page: Page, url: str) -> ParsedJob:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await jitter_sleep(500, 1200)

        role = (await text(page, "h1.app-title, h1")) or "Unknown Role"
        company = (
            await text(page, ".company-name")
            or await text(page, "[itemprop='hiringOrganization']")
            or infer_company_from_path(url)
        )
        description = await text(page, "#content, .content, .opening, .job__description, main")

        return ParsedJob(
            company=company.removeprefix("at ").strip(),
            role=role.strip(),
            description_md=description.strip(),
            apply_url=url,
            requires_account=False,  # Greenhouse public boards don't
        )

    async def fill(
        self, page: Page, plan: ApplicationPlan, *, ask: AskCallback | None = None,
    ) -> None:
        a = plan.answers
        await fill_if(page, "#first_name, input[autocomplete='given-name']", a.get("first_name"))
        await fill_if(page, "#last_name, input[autocomplete='family-name']", a.get("last_name"))
        await fill_if(page, "#email, input[type='email']", a.get("email"))
        await fill_if(page, "#phone, input[type='tel']", a.get("phone"))

        await upload_resume(
            page, plan,
            "input[type='file'][name*='resume'], input[type='file']#resume, "
            "input[type='file'][id*='resume']",
        )

        if plan.cover_letter_md:
            cl = await page.query_selector("textarea[name*='cover'], #cover_letter_text")
            if cl:
                await cl.fill(plan.cover_letter_md)

        # Custom questions (profile answers → qa_log → human via Telegram).
        await answer_groups(
            page, plan,
            group_selector=".field, .text-input-wrapper, .select, fieldset",
            label_selector="label, legend",
            ask=ask,
        )
