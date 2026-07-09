"""Tier-2 fallback wrapper. For ATSes not in the Tier-1 list.

Builds a textual task from the ParsedJob + ApplicationPlan, hands it to
tier2_browseruse.run_tier2.
"""

from __future__ import annotations

import logging

from src.ats.base import ApplicationPlan
from src.config import Settings
from src.execution.tier2_browseruse import run_tier2

log = logging.getLogger(__name__)


async def apply_with_llm(
    *,
    url: str,
    plan: ApplicationPlan,
    settings: Settings,
    dry_run: bool,
) -> dict:
    task = _build_task(plan, dry_run=dry_run)
    return await run_tier2(url=url, task=task, settings=settings)


def _build_task(plan: ApplicationPlan, *, dry_run: bool) -> str:
    answers = "\n".join(f"  {k}: {v}" for k, v in plan.answers.items() if v)
    essays = "\n".join(f"  {k}: {v[:200]}" for k, v in plan.essays.items()) or "(none)"
    submit_line = (
        "DO NOT click final submit — stop on the review/preview step."
        if dry_run else
        "After the form is filled and reviewed, click Submit."
    )
    return f"""Fill the job application at this URL.

# Known answers
{answers}

# Resume file path
{plan.resume_pdf}

# Essays
{essays}

# Rules
- Truthful answers only. Use what's provided; don't make things up.
- Upload the resume PDF into the resume field.
- {submit_line}
- If you encounter a captcha, set confidence to 0.0 so a human can take over.
- When the application is filled (and submitted if not dry-run), emit action type=done.
"""
