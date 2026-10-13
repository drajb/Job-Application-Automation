"""Detect the ATS from a job-posting URL.

Matching is on the parsed HOSTNAME (plus path where an ATS shares a host),
never on the raw string — `https://evil.example/?greenhouse.io` must not be
treated as Greenhouse, and every LinkedIn URL shape (jobs/view, comm/jobs,
lnkd.in short links) must land on Tier-3.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from src.ats.base import ATSAdapter


def _host_is(host: str, *domains: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


@dataclass
class Detection:
    ats: str  # "greenhouse" | "lever" | ... | "unknown"
    tier: str  # "tier1" | "tier2" | "tier3"


_TIER1 = {"greenhouse", "lever", "ashby", "workable", "smartrecruiters"}
_TIER3_ONLY = {"linkedin"}  # LinkedIn Easy Apply → human takeover only (docs/SPEC.md §10)


def _ats_for(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower()
    if _host_is(host, "linkedin.com", "lnkd.in"):
        return "linkedin"
    if _host_is(host, "greenhouse.io"):
        return "greenhouse"
    if host == "jobs.lever.co":
        return "lever"
    if host == "jobs.ashbyhq.com":
        return "ashby"
    if _host_is(host, "workable.com"):
        return "workable"
    if _host_is(host, "smartrecruiters.com"):
        return "smartrecruiters"
    if _host_is(host, "myworkdayjobs.com", "myworkdaysite.com", "workday.com"):
        return "workday"
    if _host_is(host, "icims.com"):
        return "icims"
    if _host_is(host, "taleo.net"):
        return "taleo"
    return "unknown"


def _tier_for(ats: str) -> str:
    if ats in _TIER3_ONLY:
        return "tier3"
    if ats in _TIER1:
        return "tier1"
    return "tier2"


def detect_from_url(url: str) -> Detection:
    ats = _ats_for(url.strip())
    return Detection(ats=ats, tier=_tier_for(ats))


def route(url: str) -> Detection:
    return detect_from_url(url)


def adapter_for(detection: Detection) -> type[ATSAdapter] | None:
    """Return the adapter class for a Tier-1 detection, else None.

    Returns None for any ATS without a dedicated tier-1 adapter; those
    fall through to the tier-2 LLM-driven flow.
    """
    if detection.ats == "greenhouse":
        from src.ats.greenhouse import GreenhouseAdapter
        return GreenhouseAdapter
    if detection.ats == "lever":
        from src.ats.lever import LeverAdapter
        return LeverAdapter
    if detection.ats == "ashby":
        from src.ats.ashby import AshbyAdapter
        return AshbyAdapter
    if detection.ats == "workable":
        from src.ats.workable import WorkableAdapter
        return WorkableAdapter
    if detection.ats == "smartrecruiters":
        from src.ats.smartrecruiters import SmartRecruitersAdapter
        return SmartRecruitersAdapter
    return None
