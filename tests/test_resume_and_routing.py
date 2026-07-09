"""Resume selection, routing, validator, preflight, ATS detection (offline)."""

from __future__ import annotations

from src.resume.selector import _route_family, list_variants, parse_jd_company_role
from src.resume.validator import bullet_diff, extract_bullets, validate


def test_route_family_director_picks_ai_manager() -> None:
    available = ["master", "ai-manager", "staff-ai-engineer", "ai-platform-pm"]
    assert _route_family("Director of AI Engineering", available) == "ai-manager"


def test_route_family_staff_picks_staff() -> None:
    available = ["master", "ai-manager", "staff-ai-engineer", "ai-platform-pm"]
    assert _route_family("Staff Machine Learning Engineer", available) == "staff-ai-engineer"


def test_route_family_pm_picks_pm() -> None:
    available = ["master", "ai-manager", "staff-ai-engineer", "ai-platform-pm"]
    assert _route_family("AI Platform Product Manager", available) == "ai-platform-pm"


def test_route_family_unknown_falls_back_to_master() -> None:
    available = ["master", "ai-manager"]
    assert _route_family("Some Generic Title", available) == "master"


def test_list_variants_excludes_historical(tmp_path) -> None:
    (tmp_path / "master").mkdir()
    (tmp_path / "historical").mkdir()
    (tmp_path / "ai-manager").mkdir()
    (tmp_path / ".build").mkdir()
    out = list_variants(tmp_path)
    assert "master" in out
    assert "ai-manager" in out
    assert "historical" not in out
    assert ".build" not in out


def test_validator_accepts_source_only_facts() -> None:
    source = "Worked at Acme Corporation in 2025. Used Python and AWS."
    tailored = "Senior Engineer at Acme Corporation (2025). Python on AWS."
    r = validate(tailored, source)
    assert r.ok, r.reason


def test_validator_rejects_fabricated_employer() -> None:
    source = "Worked at Acme Corporation."
    tailored = "Worked at Goldman Sachs and Stripe."
    r = validate(tailored, source)
    assert not r.ok
    assert any("Goldman" in e or "Stripe" in e for e in r.new_entities)


def test_validator_rejects_fabricated_year() -> None:
    source = "Joined in 2022."
    tailored = "Joined in 2019."
    r = validate(tailored, source)
    assert not r.ok
    assert "2019" in r.new_entities


def test_validator_allows_generic_terms() -> None:
    source = "Software engineer."
    tailored = "Senior Software Engineer. APIs and SDK work."
    r = validate(tailored, source)
    assert r.ok, r.reason


def test_validator_rejects_fabrication_containing_short_generic() -> None:
    # Regression: short generic tokens (ai, ml, us, ci) must NOT vouch for a
    # fabricated employer just by being a substring. "Mailchimp" contains "ai";
    # "Emailage" contains "ai" and "ml". Neither is in the source → must reject.
    source = "Worked at Acme Corporation."
    tailored = "Worked at Mailchimp and Emailage."
    r = validate(tailored, source)
    assert not r.ok
    assert any("Mailchimp" in e or "Emailage" in e for e in r.new_entities)


def test_bullet_diff_pairs_obvious_rewrites() -> None:
    src = "- Built a thing in 2024.\n- Led a team."
    tgt = "- Built a similar thing in 2024.\n- Led the team."
    pairs = bullet_diff(src, tgt)
    assert len(pairs) >= 1


def test_extract_bullets_handles_dash_and_star() -> None:
    md = "- one\n  * two\n  - three\n"
    bs = extract_bullets(md)
    assert bs == ["one", "two", "three"]


def test_parse_jd_company_role_simple() -> None:
    jd = "# Staff Engineer at Stripe\n\nWe are hiring..."
    company, role = parse_jd_company_role(jd)
    assert company == "Stripe"
    assert "Staff" in role


def test_preflight_window_returns_decision() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.orchestrator.preflight import check_window
    # 7am CT — before window
    early = datetime(2026, 6, 1, 7, 0, tzinfo=ZoneInfo("America/Chicago"))
    d = check_window(early)
    assert not d.ok and d.defer
    # noon CT — inside window
    noon = datetime(2026, 6, 1, 12, 0, tzinfo=ZoneInfo("America/Chicago"))
    d2 = check_window(noon)
    assert d2.ok


def test_preflight_company_role_hash_is_stable() -> None:
    from src.orchestrator.preflight import company_role_hash
    a = company_role_hash("Stripe", "Staff Engineer")
    b = company_role_hash("  stripe ", "Staff Engineer")
    assert a == b


def test_detector_routes_greenhouse_to_tier1() -> None:
    from src.ats.detector import detect_from_url
    d = detect_from_url("https://boards.greenhouse.io/stripe/jobs/12345")
    assert d.ats == "greenhouse"
    assert d.tier == "tier1"


def test_detector_routes_linkedin_to_tier3() -> None:
    from src.ats.detector import detect_from_url
    d = detect_from_url("https://www.linkedin.com/jobs/view/12345")
    assert d.ats == "linkedin"
    assert d.tier == "tier3"


def test_detector_unknown_routes_tier2() -> None:
    from src.ats.detector import detect_from_url
    d = detect_from_url("https://careers.example.com/jobs/12345")
    assert d.ats == "unknown"
    assert d.tier == "tier2"
