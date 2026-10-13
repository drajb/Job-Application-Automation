"""Regression tests for the safety fixes and the discovery feature (offline)."""

from __future__ import annotations

import pytest

from src.resume.validator import validate

SOURCE = """# Jane Doe
## Experience
### Acme Corporation - Senior Software Engineer (2021-present)
- Reduced latency by 30% via streaming. Used Python, Postgres and Docker.
- Mentored 4 engineers.
### Globex Systems - Software Engineer (2018-2021)
- Migrated 600+ Airflow DAGs with zero incidents.
"""


# --- validator: fabrication that used to slip through --------------------------


@pytest.mark.parametrize(
    "fabrication",
    [
        "Reduced latency by 73% via streaming.",             # changed metric
        "Saved $4M in infrastructure cost.",                 # new money figure
        "Mentored 40 engineers.",                            # inflated count
        "Used pytorch and kubernetes in production.",        # lowercase tools
        "Built pipelines on Databricks and Datadog.",        # rode in on "data"
        "Shipped integrations for Microsoft Teams.",         # rode in on "team"
        "Principal Engineer at Acme Corporation.",           # title inflation
        "Wrote services in C++.",                            # symbol-named tool
        "See https://evil.example/portfolio for more.",      # injected URL
    ],
)
def test_validator_rejects_fabrication(fabrication: str) -> None:
    r = validate(SOURCE + "\n- " + fabrication, SOURCE, check_complete=False)
    assert not r.ok, f"fabrication passed: {fabrication!r}"


def test_validator_accepts_faithful_rewrite() -> None:
    tailored = SOURCE.replace("Reduced latency by 30% via streaming.",
                              "Cut latency 30% by moving to streaming.")
    r = validate(tailored, SOURCE)
    assert r.ok, r.reason


def test_validator_allows_swapped_action_verb() -> None:
    tailored = SOURCE.replace("Migrated 600+", "Moved 600+")
    r = validate(tailored, SOURCE)
    assert r.ok, r.reason


def test_validator_rejects_empty_and_truncated_output() -> None:
    long_src = SOURCE * 4
    assert not validate("", long_src).ok
    assert not validate(long_src[:200], long_src).ok


def test_strip_fences() -> None:
    from src.resume.tailor import strip_fences
    assert strip_fences("```markdown\n# Hi\n- a\n```") == "# Hi\n- a"
    assert strip_fences("# Hi") == "# Hi"


# --- field classifier: polarity-correct answers -------------------------------


def _plan(**answers):
    from pathlib import Path

    from src.ats.base import ApplicationPlan
    base = {"authorized_us": "Yes", "requires_sponsorship": "Yes", "salary_expectation": "$150,000"}
    base.update(answers)
    return ApplicationPlan(resume_pdf=Path("x.pdf"), answers=base)


def test_sponsorship_and_authorization_polarity() -> None:
    from src.ats.fields import answer_for
    p = _plan()
    assert answer_for(p, "Will you now or in the future require visa sponsorship?") == "Yes"
    assert answer_for(p, "Are you legally authorized to work in the United States?") == "Yes"
    # Authorized, but needs sponsorship → cannot work WITHOUT sponsorship.
    assert answer_for(p, "Are you authorized to work in the US without sponsorship?") == "No"
    p2 = _plan(requires_sponsorship="No")
    assert answer_for(p2, "Are you authorized to work in the US without sponsorship?") == "Yes"


def test_sensitive_without_profile_answer_is_none() -> None:
    from src.ats.fields import answer_for, is_sensitive
    assert is_sensitive("Have you ever been convicted of a felony?")
    assert answer_for(_plan(), "Have you ever been convicted of a felony?") is None


def test_pick_option() -> None:
    from src.ats.fields import pick_option
    opts = ["Select...", "Yes, I am authorized", "No, I am not"]
    assert pick_option(opts, "Yes") == "Yes, I am authorized"
    assert pick_option(opts, "No") == "No, I am not"
    assert pick_option(["Red", "Blue"], "Green") is None


# --- detector: hostname-based ---------------------------------------------------


@pytest.mark.parametrize(
    ("url", "ats", "tier"),
    [
        ("https://www.linkedin.com/comm/jobs/view/1", "linkedin", "tier3"),
        ("https://lnkd.in/abc", "linkedin", "tier3"),
        ("https://job-boards.greenhouse.io/acme/jobs/1", "greenhouse", "tier1"),
        ("https://evil.example/?u=boards.greenhouse.io", "unknown", "tier2"),
        ("https://evilgreenhouse.io/x", "unknown", "tier2"),
    ],
)
def test_detector_uses_hostname(url, ats, tier) -> None:
    from src.ats.detector import detect_from_url
    d = detect_from_url(url)
    assert (d.ats, d.tier) == (ats, tier)


# --- Tier-2 safety -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "is_submit_type", "expected"),
    [
        ("Submit application", False, True),
        ("Send Application", False, True),
        ("Apply now", False, True),
        ("Next", True, False),
        ("Continue", True, False),
        ("", True, True),
        ("Upload resume", False, False),
    ],
)
def test_tier2_submit_detection(text, is_submit_type, expected) -> None:
    from src.execution.tier2_browseruse import is_submit_like
    assert is_submit_like(text, is_submit_type) is expected


async def test_tier2_refuses_foreign_upload_and_goto(tmp_path) -> None:
    from src.execution.tier2_browseruse import Tier2Error, _execute

    class _Page:
        async def goto(self, *_a, **_k):
            raise AssertionError("must not navigate")

    with pytest.raises(Tier2Error):
        await _execute(_Page(), {"type": "goto", "url": "https://attacker.example/x"},
                       start_site="myworkdayjobs.com", resume_pdf=tmp_path / "r.pdf")
    with pytest.raises(Tier2Error):  # resume missing → refuse, never upload something else
        await _execute(_Page(), {"type": "upload", "selector": "input"},
                       start_site="myworkdayjobs.com", resume_pdf=tmp_path / "missing.pdf")


def test_tier2_confidence_fails_closed() -> None:
    from src.execution.tier2_browseruse import _confidence
    assert _confidence({}) == 0.0
    assert _confidence({"confidence": "high"}) == 0.0
    assert _confidence({"confidence": "0.9"}) == 0.9


# --- signup correlator: anti-phishing + extraction ---------------------------------


def _mail(from_addr, subject, body, auth=""):
    from src.email_monitor.imap_idle import IncomingEmail
    return IncomingEmail(uid="9", from_addr=from_addr,
                         from_domain=from_addr.rpartition("@")[2].lower(),
                         subject=subject, body_text=body, body_html="", received_at="",
                         auth_results=auth)


def test_domain_matching_is_not_substring() -> None:
    from src.email_monitor.signup_correlator import domain_matches, registrable_domain
    assert domain_matches("mail.greenhouse.io", "greenhouse.io")
    assert not domain_matches("evilgreenhouse.io", "greenhouse.io")
    assert registrable_domain("careers.acme.co.uk") == "acme.co.uk"


def test_dkim_check() -> None:
    from src.email_monitor.signup_correlator import dkim_ok
    assert dkim_ok("mx; dkim=pass header.d=acme.com", "acme.com") is True
    assert dkim_ok("mx; dkim=fail header.d=acme.com", "acme.com") is False
    assert dkim_ok("", "acme.com") is None


def test_otp_extraction_ignores_years_and_zips() -> None:
    from src.email_monitor.signup_correlator import extract
    body = "Acme Inc, Springfield IL 62701. (c) 2026.\nYour verification code is 482913."
    assert extract(_mail("no-reply@acme.com", "Code", body), "2fa") == "482913"


def test_verify_link_must_be_on_expected_domain() -> None:
    from src.email_monitor.signup_correlator import extract
    body = ("Click https://tracker.example/click?u=1 or "
            "https://acme.com/verify?token=abc&amp;x=1.")
    link = extract(_mail("no-reply@acme.com", "Verify", body), "verify_email", "acme.com")
    assert link == "https://acme.com/verify?token=abc&x=1"


# --- classifier fallback -------------------------------------------------------------


def test_keyword_classifier() -> None:
    from src.email_monitor.classifier import classify_heuristic
    assert classify_heuristic(_mail("a@b.com", "Interview",
                                    "We'd like to schedule a call next week.")).category \
        == "interview_invite"
    assert classify_heuristic(_mail("a@b.com", "Update",
                                    "Unfortunately we will not be moving forward.")).category \
        == "rejection"
    assert classify_heuristic(_mail("a@b.com", "Thanks",
                                    "We received your application.")).category == "confirmation"


# --- discovery -------------------------------------------------------------------------


def test_parse_boards() -> None:
    from src.discovery.boards import parse_ashby, parse_greenhouse, parse_lever
    gh = parse_greenhouse({"jobs": [{
        "title": "Senior Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
        "location": {"name": "Remote - US"}, "content": "&lt;p&gt;Python &amp;amp; AWS&lt;/p&gt;",
        "first_published": "2026-09-01T00:00:00Z",
    }]}, "acme")
    assert gh[0].remote and "Python" in gh[0].description and gh[0].company == "Acme"
    lv = parse_lever([{"text": "Staff Eng", "hostedUrl": "https://jobs.lever.co/acme/1",
                       "categories": {"location": "NYC"}, "createdAt": 1_700_000_000_000,
                       "descriptionPlain": "Go"}], "acme")
    assert lv[0].title == "Staff Eng" and lv[0].posted_at is not None
    ab = parse_ashby({"jobs": [{"title": "PM", "jobUrl": "https://jobs.ashbyhq.com/acme/1",
                                "isListed": False}]}, "acme")
    assert ab == []


def test_fit_and_keyword_gap() -> None:
    from src.discovery.fit import score_fit
    rep = score_fit("We need Python, Kubernetes and Terraform experience.",
                    "Built services in Python on Kubernetes.")
    assert "python" in rep.matched and "kubernetes" in rep.matched
    assert "terraform" in rep.missing
    assert 0 < rep.percent < 100


def test_watchlist_validation_and_filters() -> None:
    from src.discovery.boards import Posting
    from src.discovery.watchlist import WatchlistError, parse

    wl = parse({"companies": [{"ats": "greenhouse", "slug": "acme"}],
                "filters": {"title_include": ["engineer"], "title_exclude": ["intern"],
                            "locations": ["New York"], "remote_ok": True}})
    ok = Posting("greenhouse", "Acme", "Senior Engineer", "Remote", "u", remote=True)
    intern = Posting("greenhouse", "Acme", "Engineer Intern", "New York", "u")
    elsewhere = Posting("greenhouse", "Acme", "Engineer", "Berlin", "u")
    assert wl.filters.accepts(ok)
    assert not wl.filters.accepts(intern)
    assert not wl.filters.accepts(elsewhere)
    with pytest.raises(WatchlistError):
        parse({"companies": [{"ats": "workday", "slug": "x"}]})


def test_example_watchlist_is_valid() -> None:
    from pathlib import Path

    from src.discovery.watchlist import load
    wl = load(Path(__file__).resolve().parents[1] / "watchlist.example.yaml")
    assert wl.boards


# --- cards render as valid Telegram HTML ---------------------------------------------


def test_cards_escape_html() -> None:
    from src.telegram_bot.cards import approval_card, pause_card
    c = approval_card(app_id=3, company="A&B <Corp>", role="Eng #1", ats="greenhouse",
                      tier="tier1", resume_name="x.pdf", variant="master", resume_uuid="u",
                      validator_ok=True, diffs=[("old <b>", "new & better")], dry_run=True)
    assert "A&amp;B &lt;Corp&gt;" in c.text and "<b>A&amp;B" in c.text
    assert "new &amp; better" in c.text
    assert "DRY RUN" in c.text
    p = pause_card(5, "Salary <expectation>?")
    assert "&lt;expectation&gt;" in p.text


# --- password generator / CSV ---------------------------------------------------------


def test_password_never_starts_with_formula_char() -> None:
    from src.accounts.password_gen import generate_password
    for _ in range(300):
        pw = generate_password(24)
        assert pw[0].isalnum() and len(pw) == 24
        assert any(c.isdigit() for c in pw) and any(not c.isalnum() for c in pw)


def test_csv_cell_neutralises_formulas() -> None:
    from src.accounts.vault import _cell
    assert _cell("=cmd()") == "'=cmd()"
    assert _cell("abc") == "abc"
