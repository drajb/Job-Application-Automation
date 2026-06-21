"""Pre-flight filters per docs/SPEC.md §6.5.

Runs BEFORE tailoring so we don't waste Gemini tokens. Returns a PreflightDecision
with .skip / .defer / .ok + a human-readable reason.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from src.db.models import Application, SponsorH1B
from src.db.session import get_session
from src.util.time import utcnow

log = logging.getLogger(__name__)

CT = ZoneInfo("America/Chicago")
SUBMIT_WINDOW_START = 10  # 10am CT
SUBMIT_WINDOW_END = 18    # 6pm CT
DAILY_CAP = 25
COOLDOWN_DAYS = 90


@dataclass
class PreflightDecision:
    ok: bool
    defer: bool  # True if we should retry later (window/cap), False if hard skip
    reason: str

    @classmethod
    def passing(cls) -> PreflightDecision:
        return cls(ok=True, defer=False, reason="preflight: all checks passed")

    @classmethod
    def skip(cls, reason: str) -> PreflightDecision:
        return cls(ok=False, defer=False, reason=reason)

    @classmethod
    def deferred(cls, reason: str) -> PreflightDecision:
        return cls(ok=False, defer=True, reason=reason)


def company_role_hash(company: str, role: str) -> str:
    s = f"{company.strip().lower()}|{role.strip().lower()}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def check_window(now: datetime | None = None) -> PreflightDecision:
    now_ct = (now or datetime.now(CT)).astimezone(CT)
    if not (SUBMIT_WINDOW_START <= now_ct.hour < SUBMIT_WINDOW_END):
        return PreflightDecision.deferred(
            f"outside submission window 10am-6pm CT (now: {now_ct:%H:%M %Z})",
        )
    return PreflightDecision.passing()


def check_daily_cap() -> PreflightDecision:
    today = datetime.now(CT).date()
    with get_session() as s:
        count = s.scalar(
            select(func.count(Application.id)).where(
                func.date(Application.applied_at) == today,
                Application.status.in_(("submitted", "response", "interview", "offer")),
            ),
        ) or 0
    if count >= DAILY_CAP:
        return PreflightDecision.deferred(
            f"daily cap reached ({count}/{DAILY_CAP}). Try tomorrow.",
        )
    return PreflightDecision.passing()


def check_cooldown(company: str, role: str) -> PreflightDecision:
    cutoff = utcnow() - timedelta(days=COOLDOWN_DAYS)
    with get_session() as s:
        recent = s.scalar(
            select(Application).where(
                Application.company == company,
                Application.role_title == role,
                Application.applied_at >= cutoff,
            ).limit(1),
        )
    if recent is not None:
        return PreflightDecision.skip(
            f"cooldown: applied to {company}/{role} within last {COOLDOWN_DAYS} days "
            f"(application #{recent.id} on {recent.applied_at.date() if recent.applied_at else 'unknown'})",
        )
    return PreflightDecision.passing()


def check_h1b_sponsor(company: str, *, strict: bool = False) -> PreflightDecision:
    """Pre-filter companies with zero recent H1B sponsorships.

    Not strict by default — many small/new companies aren't in the dataset and
    may still sponsor. Set strict=True once your sponsor dataset is solid.
    """
    with get_session() as s:
        row = s.scalar(
            select(SponsorH1B).where(SponsorH1B.company.ilike(f"%{company.strip()}%")).limit(1),
        )
    if row is None:
        if strict:
            return PreflightDecision.skip(
                f"{company} not in H1B sponsor dataset (strict mode).",
            )
        return PreflightDecision.passing()
    if (row.sponsored_count or 0) <= 0:
        return PreflightDecision.skip(
            f"{company} has zero recent H1B sponsorships per dataset.",
        )
    return PreflightDecision.passing()


def check_salary_floor(
    posting_max: int | None, *, desired_min: int,
) -> PreflightDecision:
    if posting_max is not None and posting_max < desired_min:
        return PreflightDecision.skip(
            f"posting max ${posting_max:,} < desired min ${desired_min:,}",
        )
    return PreflightDecision.passing()


def run_all(
    *,
    company: str,
    role: str,
    desired_base_min: int,
    posting_max: int | None = None,
    check_strict_sponsor: bool = False,
) -> PreflightDecision:
    """Run every pre-flight check in order. First failure wins."""
    for check in (
        check_window(),
        check_daily_cap(),
        check_cooldown(company, role),
        check_h1b_sponsor(company, strict=check_strict_sponsor),
        check_salary_floor(posting_max, desired_min=desired_base_min),
    ):
        if not check.ok:
            return check
    return PreflightDecision.passing()
