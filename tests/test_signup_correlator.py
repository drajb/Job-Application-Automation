"""Signup correlator + email-expectation lifecycle (no live IMAP)."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _ephemeral_db(tmp_path, monkeypatch):
    db_path = tmp_path / "phase3.db"
    monkeypatch.setattr("src.config.DB_PATH", db_path)
    monkeypatch.setattr("src.db.session.DB_PATH", db_path)
    from src.db import session
    session.get_engine.cache_clear()
    session._session_factory.cache_clear()
    from alembic import command
    from alembic.config import Config
    cfg = Config()
    cfg.set_main_option("script_location", "src/db/migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")
    yield
    session.get_engine.cache_clear()
    session._session_factory.cache_clear()


def _fake_msg(from_addr, subject, body):
    from src.email_monitor.imap_idle import IncomingEmail
    return IncomingEmail(
        uid="1", from_addr=from_addr,
        from_domain=from_addr.rpartition("@")[2].lower(),
        subject=subject, body_text=body, body_html="", received_at="",
    )


def test_expectation_create_and_match() -> None:
    from src.email_monitor.signup_correlator import create_expectation, match_and_fulfill

    eid = create_expectation(
        application_id=None,
        expected_sender_domain="greenhouse.io",
        purpose="verify_email",
        expected_subject_regex=r"verify.*email",
    )
    msg = _fake_msg(
        "noreply@boards.greenhouse.io",
        "Please verify your email",
        "Click https://boards.greenhouse.io/verify?token=abc to confirm.",
    )
    mid = match_and_fulfill(msg)
    assert mid == eid


def test_expectation_subject_mismatch_does_not_fulfill() -> None:
    from src.email_monitor.signup_correlator import create_expectation, match_and_fulfill

    create_expectation(
        application_id=None,
        expected_sender_domain="greenhouse.io",
        purpose="verify_email",
        expected_subject_regex=r"verify.*email",
    )
    msg = _fake_msg(
        "noreply@boards.greenhouse.io",
        "Welcome to Greenhouse",
        "Click https://example.com/welcome",
    )
    mid = match_and_fulfill(msg)
    assert mid is None


def test_expectation_2fa_extracts_otp() -> None:
    from src.db.models import EmailExpectation
    from src.db.session import get_session
    from src.email_monitor.signup_correlator import create_expectation, match_and_fulfill

    eid = create_expectation(
        application_id=None,
        expected_sender_domain="lever.co",
        purpose="2fa",
    )
    msg = _fake_msg("noreply@lever.co", "Your code", "Your code is 482913 (valid 10 min).")
    mid = match_and_fulfill(msg)
    assert mid == eid
    with get_session() as s:
        row = s.get(EmailExpectation, eid)
        assert row.fulfilled is True
        assert row.fulfilled_data == "482913"


def test_password_gen_only_long_enough() -> None:
    from src.accounts.password_gen import generate_password
    p = generate_password(20)
    assert len(p) == 20
    with pytest.raises(ValueError):
        generate_password(5)
