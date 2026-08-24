"""LinkedIn helpers: session detection, referral ranking. No live calls."""

from __future__ import annotations


def test_referral_scan_ranking_prefers_recruiter() -> None:
    from src.linkedin.referral_scan import _rank
    a = _rank("Senior Recruiter at Stripe", "Stripe")
    b = _rank("Software Engineer at Stripe", "Stripe")
    c = _rank("Marketing Director at FoodCo", "Stripe")
    assert a > b > c


def test_session_check_returns_false_when_absent(tmp_path, monkeypatch) -> None:
    from src.linkedin import session
    fake = tmp_path / "nope" / "storage_state.json"
    monkeypatch.setattr(session, "SESSION_PATH", fake)
    assert session.has_session() is False


def test_session_check_true_for_valid_state(tmp_path, monkeypatch) -> None:
    import json

    from src.linkedin import session
    fake = tmp_path / "ls" / "storage_state.json"
    fake.parent.mkdir(parents=True)
    fake.write_text(json.dumps({"cookies": [{"name": "li_at", "value": "abc"}]}))
    monkeypatch.setattr(session, "SESSION_PATH", fake)
    assert session.has_session() is True


def test_easy_apply_module_imports_without_session() -> None:
    # Import-time check: module loads even when no session file exists.
    from src.linkedin import easy_apply  # noqa: F401
