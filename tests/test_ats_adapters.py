"""ATS detection + adapter wiring (no live browser)."""

from __future__ import annotations


def test_detect_lever() -> None:
    from src.ats.detector import detect_from_url
    d = detect_from_url("https://jobs.lever.co/anthropic/abc-123")
    assert d.ats == "lever"
    assert d.tier == "tier1"


def test_detect_ashby() -> None:
    from src.ats.detector import detect_from_url
    d = detect_from_url("https://jobs.ashbyhq.com/scale/abc-123")
    assert d.ats == "ashby"
    assert d.tier == "tier1"


def test_detect_workable() -> None:
    from src.ats.detector import detect_from_url
    d = detect_from_url("https://apply.workable.com/some-co/j/ABC123/")
    assert d.ats == "workable"
    assert d.tier == "tier1"


def test_detect_smartrecruiters() -> None:
    from src.ats.detector import detect_from_url
    d = detect_from_url("https://jobs.smartrecruiters.com/example/123")
    assert d.ats == "smartrecruiters"
    assert d.tier == "tier1"


def test_detect_workday_routes_tier2() -> None:
    from src.ats.detector import detect_from_url
    d = detect_from_url("https://example.wd1.myworkdayjobs.com/en-US/careers/job/123")
    assert d.ats == "workday"
    assert d.tier == "tier2"


def test_adapter_for_returns_class() -> None:
    from src.ats.detector import Detection, adapter_for
    assert adapter_for(Detection(ats="lever", tier="tier1")).__name__ == "LeverAdapter"
    assert adapter_for(Detection(ats="ashby", tier="tier1")).__name__ == "AshbyAdapter"
    assert adapter_for(Detection(ats="workable", tier="tier1")).__name__ == "WorkableAdapter"
    assert adapter_for(Detection(ats="smartrecruiters", tier="tier1")).__name__ == "SmartRecruitersAdapter"
    assert adapter_for(Detection(ats="unknown", tier="tier2")) is None


def test_adapter_can_handle_each() -> None:
    from src.ats.ashby import AshbyAdapter
    from src.ats.lever import LeverAdapter
    from src.ats.smartrecruiters import SmartRecruitersAdapter
    from src.ats.workable import WorkableAdapter
    assert LeverAdapter.can_handle("https://jobs.lever.co/x/y")
    assert AshbyAdapter.can_handle("https://jobs.ashbyhq.com/x/y")
    assert WorkableAdapter.can_handle("https://apply.workable.com/x/y")
    assert SmartRecruitersAdapter.can_handle("https://jobs.smartrecruiters.com/x")
    assert not LeverAdapter.can_handle("https://greenhouse.io/x")


def test_llm_fallback_task_dry_run() -> None:
    from pathlib import Path

    from src.ats.base import ApplicationPlan
    from src.ats.llm_fallback import _build_task
    plan = ApplicationPlan(
        resume_pdf=Path("/tmp/x.pdf"),
        answers={"first_name": "Jane", "email": "jane.doe@example.com"},
    )
    t = _build_task(plan, dry_run=True)
    assert "DO NOT click final submit" in t
    assert "Jane" in t
    t2 = _build_task(plan, dry_run=False)
    assert "click Submit" in t2
