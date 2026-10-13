"""Tier-2 fallback wrapper. For ATSes not in the Tier-1 list.

Builds a textual task from the ApplicationPlan and hands it, together with an
open page, to tier2_browseruse.run_tier2. The loop fills the form and stops at
"ready" — it never submits (see tier2_browseruse's module docstring).
"""

from __future__ import annotations

import logging

from src.ats.base import ApplicationPlan
from src.config import Settings
from src.execution.tier2_browseruse import run_tier2

log = logging.getLogger(__name__)

# Never put these into the LLM prompt.
_PRIVATE_KEYS = {"salary_expectation"}


async def apply_with_llm(
    *,
    page,
    url: str,
    plan: ApplicationPlan,
    settings: Settings,
    client=None,
) -> dict:
    task = _build_task(plan)
    return await run_tier2(
        page=page, url=url, task=task, settings=settings,
        resume_pdf=plan.resume_pdf, client=client,
    )


def _build_task(plan: ApplicationPlan) -> str:
    answers = "\n".join(
        f"  {k}: {v}" for k, v in plan.answers.items() if v and k not in _PRIVATE_KEYS
    )
    essays = "\n".join(f"  {k}: {v[:200]}" for k, v in plan.essays.items()) or "  (none)"
    return f"""Fill in the job application on this site for the candidate below.

# Known answers
{answers}

# Essays
{essays}

# Rules
- Truthful answers only. Use what's provided; never make anything up.
- Upload the resume into the resume / CV file field.
- Salary, criminal-history, security-clearance and legal questions, and any
  question not answered above: set confidence below 0.7 so a human answers it.
- If you encounter a captcha or a login wall, set confidence to 0.0.
- Do NOT click the final submit button. When the form is complete, return
  type=ready with the submit button's selector.
"""
