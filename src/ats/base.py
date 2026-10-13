"""Base ATS adapter contract.

Tier-1 adapters subclass this. Tier-2 (src/execution/tier2_browseruse.py)
drives the same two phases with an LLM instead of fixed selectors.

The contract is split in two so the human approves what will ACTUALLY be sent:

  1. fill(page, plan, ask=...)  — fill every field. NEVER clicks Submit.
  2. (orchestrator screenshots the filled form → Telegram approval → re-checks
     the submission window and daily cap → only then, and only if dry_run is
     off) submit(page) — click Submit and confirm the ATS accepted it.

Putting the submit click in its own method means "dry run" is enforced by
the orchestrator in one place, not re-implemented (and forgotten) per adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Page

# Callback an adapter invokes when it hits a field it has no answer for.
# Given the field's label text, it returns an answer (from the learned qa_log
# or a human's Telegram reply) or None to leave the field blank. The
# orchestrator supplies this; it also persists any human answer for reuse.
AskCallback = Callable[[str], Awaitable[str | None]]


class SubmitError(RuntimeError):
    """Submit button missing or the click failed."""


@dataclass
class ParsedJob:
    company: str
    role: str
    location: str | None = None
    description_md: str = ""
    posted_at: str | None = None  # ISO date if extractable
    salary_min: int | None = None
    salary_max: int | None = None
    apply_url: str = ""
    requires_account: bool = False


@dataclass
class ApplicationPlan:
    """What the agent will submit. Built BEFORE clicking Submit."""

    resume_pdf: Path
    cover_letter_md: str | None = None
    answers: dict[str, str] = field(default_factory=dict)  # field_label → answer
    essays: dict[str, str] = field(default_factory=dict)
    notes: str = ""


class ATSAdapter(ABC):
    """Tier-1 deterministic adapter. Subclasses fill in selectors + flow."""

    name: str = "base"
    # Tried in order by the default submit(). Override per ATS.
    submit_selectors: tuple[str, ...] = (
        "button[type='submit']",
        "input[type='submit']",
    )

    @classmethod
    @abstractmethod
    def can_handle(cls, url: str, page: Page | None = None) -> bool: ...

    @abstractmethod
    async def parse_job(self, page: Page, url: str) -> ParsedJob: ...

    @abstractmethod
    async def fill(
        self,
        page: Page,
        plan: ApplicationPlan,
        *,
        ask: AskCallback | None = None,
    ) -> None:
        """Fill all fields. MUST NOT click the final submit button.

        `ask` (optional): called with a field label the adapter can't answer
        from `plan`. Returns an answer to fill, or None to skip. When absent,
        unknown fields are simply skipped.
        """

    async def submit(self, page: Page) -> bool:
        """Click Submit. Returns True when the ATS confirmed the submission,
        False when the click happened but no confirmation was seen.
        Raises SubmitError when there is nothing to click."""
        from src.ats.common import click_submit, wait_for_confirmation

        before = page.url
        await click_submit(page, self.submit_selectors)
        return await wait_for_confirmation(page, before)
