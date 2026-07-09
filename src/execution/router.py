"""Execution router. Picks tier per detection and runs the right handler.

Keeps the orchestrator clean: it asks the router to run an application and
the router dispatches to the right tier (1 deterministic / 2 LLM / 3 manual).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.ats.detector import Detection
from src.config import Settings

log = logging.getLogger(__name__)


@dataclass
class RouteResult:
    tier_used: str  # "tier1" | "tier2" | "tier3"
    ok: bool
    payload: dict


async def run_application(
    *,
    detection: Detection,
    url: str,
    task: str,
    settings: Settings,
) -> RouteResult:
    if detection.tier == "tier1":
        return RouteResult(tier_used="tier1", ok=True, payload={"note": "use ATS adapter directly"})
    if detection.tier == "tier2":
        from src.execution.tier2_browseruse import run_tier2
        result = await run_tier2(url=url, task=task, settings=settings)
        ok = result.get("status") == "done"
        return RouteResult(tier_used="tier2", ok=ok, payload=result)
    # tier3 — caller must invoke request_handoff with a page handle
    return RouteResult(tier_used="tier3", ok=False, payload={"note": "manual takeover required"})
