"""Per-variant response-rate stats + training analyzer + sponsor seed."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.util.time import utcnow


@pytest.fixture(autouse=True)
def _ephemeral_db(tmp_path, monkeypatch):
    db_path = tmp_path / "phase6.db"
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


def _seed_app(company, variant, has_interview=False):
    import hashlib

    from src.db.models import Application, ResponseLog
    from src.db.session import get_session
    url = f"https://x.com/{company}/{variant}"
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    with get_session() as s:
        a = Application(
            url=url, url_hash=h, company=company,
            role_title="Engineer", ats="greenhouse", tier_used="tier1",
            status="submitted",
            applied_at=utcnow() - timedelta(days=5),
            resume_pdf=f"data/tailored/abc123__{variant}__co__role.pdf",
        )
        s.add(a)
        s.commit()
        if has_interview:
            rl = ResponseLog(
                application_id=a.id, email_uid="z", from_addr="r@co.com",
                subject="Next steps", body_excerpt="...",
                category="interview_invite",
                classified_at=utcnow(),
                notified=True,
            )
            s.add(rl)
            s.commit()
        return a.id


def test_rate_tracker_returns_per_variant() -> None:
    from src.observability.rate_tracker import response_rate_by_variant
    _seed_app("Stripe", "staff-ai-engineer", has_interview=True)
    _seed_app("Anthropic", "staff-ai-engineer", has_interview=False)
    _seed_app("OpenAI", "ai-manager", has_interview=False)
    rows = response_rate_by_variant()
    by = {r["variant"]: r for r in rows}
    assert by["staff-ai-engineer"]["submitted"] == 2
    assert by["staff-ai-engineer"]["positive"] == 1
    assert by["staff-ai-engineer"]["rate"] == 0.5
    assert by["ai-manager"]["rate"] == 0.0


def test_variant_from_pdf_parses_correct() -> None:
    from src.observability.rate_tracker import _variant_from_pdf
    assert _variant_from_pdf("data/tailored/abc123__staff-ai-engineer__co__role.pdf") == "staff-ai-engineer"
    assert _variant_from_pdf(None) is None
    assert _variant_from_pdf("weirdpath.pdf") is None


def test_training_analyzer_writes_report(tmp_path) -> None:
    from scripts.analyze_training import collect_recent, group_by_question, write_report
    from src.db.models import TrainingRun
    from src.db.session import get_session

    with get_session() as s:
        for i in range(3):
            s.add(TrainingRun(
                application_id=None,
                step_number=i,
                question="Will you require sponsorship?",
                agent_action="pause",
                human_action="Yes — H1B",
                intervened=True,
                timestamp=utcnow(),
            ))
        s.commit()

    rows = collect_recent()
    groups = group_by_question(rows)
    assert "Will you require sponsorship?" in groups
    path = write_report(groups, tmp_path)
    assert path.exists()
    content = path.read_text()
    assert "sponsorship" in content.lower()
    assert "count: 3" in content


def test_sponsor_seed_round_trips(tmp_path) -> None:
    from scripts.seed_sponsors import seed
    csv_path = tmp_path / "sponsors.csv"
    csv_path.write_text("company,sponsored_count,last_seen_year\nStripe,42,2024\nAnthropic,17,2025\n")
    rc = seed(csv_path)
    assert rc == 0
    from sqlalchemy import select

    from src.db.models import SponsorH1B
    from src.db.session import get_session
    with get_session() as s:
        rows = list(s.scalars(select(SponsorH1B)))
    assert {r.company for r in rows} == {"Stripe", "Anthropic"}
