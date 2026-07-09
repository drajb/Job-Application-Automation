"""Base ATS adapter contract.

Tier-1 adapters subclass this. Tier-2 (browser-use) has a different shape; it
just gets handed a URL and the field-question set.
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
        dry_run: bool,
        ask: AskCallback | None = None,
    ) -> None:
        """Fill all fields. If dry_run, do NOT click final submit.

        `ask` (optional): called with a field label the adapter can't answer
        from `plan`. Returns an answer to fill, or None to skip. When absent,
        unknown fields are simply skipped.
        """
