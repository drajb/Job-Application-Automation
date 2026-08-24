"""Detect the ATS from a job-posting URL (and optionally page markup)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from src.ats.base import ATSAdapter

# Tier-1 ATSes with dedicated deterministic adapters.
_URL_PATTERNS: list[tuple[str, str]] = [
    ("greenhouse", r"(boards\.greenhouse\.io|job-boards\.greenhouse\.io|greenhouse\.io/jobs)"),
    ("lever",      r"(jobs\.lever\.co)"),
    ("ashby",      r"(jobs\.ashbyhq\.com)"),
    ("workable",   r"(apply\.workable\.com)"),
    ("smartrecruiters", r"(jobs\.smartrecruiters\.com|smartrecruiters\.com/api)"),
    ("workday",    r"(myworkdayjobs\.com|workday\.com)"),
    ("icims",      r"(icims\.com)"),
    ("taleo",      r"(taleo\.net)"),
    ("linkedin",   r"(linkedin\.com/jobs)"),
]


@dataclass
class Detection:
    ats: str  # "greenhouse" | "lever" | ... | "unknown"
    tier: str  # "tier1" | "tier2" | "tier3"


def detect_from_url(url: str) -> Detection:
    host = urlparse(url).netloc + urlparse(url).path
    for ats, pattern in _URL_PATTERNS:
        if re.search(pattern, host):
            tier = _tier_for(ats)
            return Detection(ats=ats, tier=tier)
    return Detection(ats="unknown", tier="tier2")


_TIER1 = {"greenhouse", "lever", "ashby", "workable", "smartrecruiters"}
_TIER3_ONLY = {"linkedin"}  # LinkedIn Easy Apply → human takeover only (docs/SPEC.md §10)


def _tier_for(ats: str) -> str:
    if ats in _TIER3_ONLY:
        return "tier3"
    if ats in _TIER1:
        return "tier1"
    return "tier2"


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
