"""Pre-flight filters per docs/SPEC.md §6.5.

Runs BEFORE tailoring so we don't waste Gemini tokens. Returns a PreflightDecision
with .skip / .defer / .ok + a human-readable reason.

The window and daily-cap checks run AGAIN immediately before the submit click
(`check_submit_gates`), because a human approval can take minutes and parallel
runs could otherwise race past the cap.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select

from src.config import COOLDOWN_DAYS, DAILY_CAP, LOCAL_TZ, SUBMIT_WINDOW_END, SUBMIT_WINDOW_START
from src.db.models import Application, SponsorH1B
from src.db.session import get_session
from src.util.time import local_day_bounds_utc, utcnow

log = logging.getLogger(__name__)

# Statuses that count as "an application went out".
SUBMITTED_STATUSES = ("submitted", "submit_unverified", "response", "interview", "offer")

# Re-exported for callers/tests that still reference the old names.
SUBMIT_WINDOW_START_HOUR = SUBMIT_WINDOW_START
SUBMIT_WINDOW_END_HOUR = SUBMIT_WINDOW_END


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


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def company_role_hash(company: str, role: str) -> str:
    s = f"{normalize(company)}|{normalize(role)}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def check_window(now: datetime | None = None) -> PreflightDecision:
    now_local = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ)
    if not (SUBMIT_WINDOW_START <= now_local.hour < SUBMIT_WINDOW_END):
        return PreflightDecision.deferred(
            f"outside submission window {SUBMIT_WINDOW_START}:00-{SUBMIT_WINDOW_END}:00 "
            f"{LOCAL_TZ.key} (now: {now_local:%H:%M %Z})",
        )
    return PreflightDecision.passing()


def submitted_today() -> int:
    start, end = local_day_bounds_utc()
    with get_session() as s:
        return s.scalar(
            select(func.count(Application.id)).where(
                Application.applied_at >= start,
                Application.applied_at < end,
                Application.status.in_(SUBMITTED_STATUSES),
            ),
        ) or 0


def check_daily_cap() -> PreflightDecision:
    count = submitted_today()
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
                func.lower(func.trim(Application.company)) == normalize(company),
                func.lower(func.trim(Application.role_title)) == normalize(role),
                Application.applied_at.is_not(None),
                Application.applied_at >= cutoff,
            ).order_by(Application.applied_at.desc()).limit(1),
        )
    if recent is not None:
        return PreflightDecision.skip(
            f"cooldown: applied to {company}/{role} within last {COOLDOWN_DAYS} days "
            f"(application #{recent.id} on {recent.applied_at:%Y-%m-%d})",
        )
    return PreflightDecision.passing()


_SUFFIX_RE = re.compile(
    r"[,.]?\s+(inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|plc|gmbh|"
    r"technologies|technology|labs|holdings|group)\.?$",
)


def _company_key(name: str) -> str:
    key = normalize(name)
    prev = None
    while prev != key:
        prev = key
        key = _SUFFIX_RE.sub("", key).strip()
    return key


def check_h1b_sponsor(company: str, *, strict: bool = False) -> PreflightDecision:
    """Pre-filter companies with zero recent H1B sponsorships.

    Matches on the normalised company name (case, whitespace and corporate
    suffixes ignored) — never a loose substring, so "Meta" can't match an
    unrelated "Metamorphic Inc". Not strict by default: many small/new
    companies aren't in the dataset and may still sponsor.
    """
    key = _company_key(company)
    if not key:
        return PreflightDecision.passing()
    escaped = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with get_session() as s:
        rows = list(s.scalars(
            select(SponsorH1B).where(or_(
                func.lower(SponsorH1B.company) == key,
                func.lower(SponsorH1B.company).like(f"{escaped} %", escape="\\"),
                func.lower(SponsorH1B.company).like(f"{escaped},%", escape="\\"),
            )).limit(20),
        ))
    rows = [r for r in rows if _company_key(r.company) == key]
    if not rows:
        if strict:
            return PreflightDecision.skip(f"{company} not in H1B sponsor dataset (strict mode).")
        return PreflightDecision.passing()
    if max((r.sponsored_count or 0) for r in rows) <= 0:
        return PreflightDecision.skip(f"{company} has zero recent H1B sponsorships per dataset.")
    return PreflightDecision.passing()


def check_salary_floor(
    posting_max: int | None, *, desired_min: int,
) -> PreflightDecision:
    if posting_max is not None and posting_max < desired_min:
        return PreflightDecision.skip(
            f"posting max ${posting_max:,} < desired min ${desired_min:,}",
        )
    return PreflightDecision.passing()


def check_quota_headroom() -> PreflightDecision:
    """Defer new applications once 80% of the daily Gemini budget is used, so
    email classification and signups keep working (docs/SPEC.md §6.5 #7)."""
    from src.llm.rate_limiter import get_rate_limiter

    lim = get_rate_limiter()
    if lim.day_calls >= int(lim.rpd_limit * 0.8):
        return PreflightDecision.deferred(
            f"Gemini daily quota at {lim.day_calls}/{lim.rpd_limit} — new applications "
            f"resume after the daily reset.",
        )
    return PreflightDecision.passing()


def check_submit_gates() -> PreflightDecision:
    """Last-moment checks right before clicking Submit."""
    for check in (check_window(), check_daily_cap()):
        if not check.ok:
            return check
    return PreflightDecision.passing()


def run_all(
    *,
    company: str,
    role: str,
    desired_base_min: int,
    posting_max: int | None = None,
    check_strict_sponsor: bool = False,
    check_sponsor: bool = True,
) -> PreflightDecision:
    """Run every pre-flight check in order. First failure wins."""
    checks = [
        check_window,
        check_daily_cap,
        lambda: check_cooldown(company, role),
        lambda: check_h1b_sponsor(company, strict=check_strict_sponsor) if check_sponsor
        else PreflightDecision.passing(),
        lambda: check_salary_floor(posting_max, desired_min=desired_base_min),
        check_quota_headroom,
    ]
    for check in checks:
        d = check()
        if not d.ok:
            return d
    return PreflightDecision.passing()
