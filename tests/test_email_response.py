"""Email response matcher + daily digest (no live LLM)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.util.time import utcnow


@pytest.fixture(autouse=True)
def _ephemeral_db(tmp_path, monkeypatch):
    db_path = tmp_path / "phase5.db"
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


def _seed_application(company, role, days_ago=3):
    import hashlib

    from src.db.models import Application
    from src.db.session import get_session
    url = f"https://boards.greenhouse.io/{company.lower()}/jobs/{role}"
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    with get_session() as s:
        row = Application(
            url=url,
            url_hash=h,
            company=company, role_title=role,
            ats="greenhouse", tier_used="tier1",
            status="submitted",
            applied_at=utcnow() - timedelta(days=days_ago),
        )
        s.add(row)
        s.commit()
        return row.id


def _fake_msg(from_addr, subject, body):
    from src.email_monitor.imap_idle import IncomingEmail
    return IncomingEmail(
        uid="1", from_addr=from_addr,
        from_domain=from_addr.rpartition("@")[2].lower(),
        subject=subject, body_text=body, body_html="", received_at="",
    )


def test_matcher_finds_by_sender_domain() -> None:
    from src.email_monitor.matcher import match
    _seed_application("Stripe", "Staff Engineer")
    msg = _fake_msg("jordan@stripe.com", "Next steps", "Hi, would love to chat.")
    app = match(msg)
    assert app is not None
    assert app.company == "Stripe"


def test_matcher_finds_by_subject_text() -> None:
    from src.email_monitor.matcher import match
    _seed_application("Anthropic", "Member of Technical Staff")
    # Domain doesn't match (some random recruiting platform).
    msg = _fake_msg("noreply@recruitee.com", "Update on Anthropic application", "Hi Jane...")
    app = match(msg)
    assert app is not None
    assert app.company == "Anthropic"


def test_matcher_orphan_returns_none() -> None:
    from src.email_monitor.matcher import match
    _seed_application("Stripe", "Staff Engineer")
    msg = _fake_msg("recruiter@example.com", "Opportunity at DocCorp", "Cold outreach text")
    app = match(msg)
    assert app is None


def test_digest_text_has_sections() -> None:
    from src.observability.digest import build_digest_text
    _seed_application("Stripe", "X", days_ago=0)
    _seed_application("Stripe", "Y", days_ago=1)
    text = build_digest_text()
    assert "Submissions" in text
    assert "Responses" in text


def test_classification_high_priority_set() -> None:
    from src.email_monitor.classifier import HIGH_PRIORITY
    assert {"interview_invite", "recruiter_outreach", "offer"} == HIGH_PRIORITY
