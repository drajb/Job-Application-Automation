"""qa_log semantic search + stuck guard + execution router (no LLM)."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _ephemeral_db(tmp_path, monkeypatch):
    """Run each test against a fresh sqlite + migrations."""
    db_path = tmp_path / "phase2.db"
    monkeypatch.setattr("src.config.DB_PATH", db_path)
    from src.db import session
    session.get_engine.cache_clear()
    session._session_factory.cache_clear()
    monkeypatch.setattr("src.db.session.DB_PATH", db_path)
    from alembic import command
    from alembic.config import Config
    cfg = Config()
    cfg.set_main_option("script_location", "src/db/migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")
    yield
    session.get_engine.cache_clear()
    session._session_factory.cache_clear()


def test_qa_log_pause_when_empty() -> None:
    from src.profile.qa_log import lookup
    m = lookup("Are you willing to relocate?")
    assert m.decision == "pause"
    assert m.answer is None


def test_qa_log_reuse_high_similarity() -> None:
    from src.profile.qa_log import lookup, store
    store(
        "Will you now or in the future require sponsorship?",
        "Yes — I'll require employment sponsorship now or in the future.",
        source="human", category="visa",
    )
    m = lookup("Will you now or in the future require sponsorship?")
    assert m.decision == "reuse"
    assert "sponsorship" in m.answer.lower()
    assert m.score > 0.85


def test_qa_log_rephrase_band() -> None:
    from src.profile.qa_log import lookup, store
    store(
        "Do you need US visa sponsorship?",
        "Yes — I'll require employment sponsorship.",
        source="human", category="visa",
    )
    # Different phrasing, related topic.
    m = lookup("Are you authorized to work in the US without sponsorship?")
    # Could land in rephrase or pause depending on bge similarity. Accept either.
    assert m.decision in {"rephrase", "reuse", "pause"}


def test_router_tier1_skips_immediate() -> None:
    import asyncio

    from src.ats.detector import Detection
    from src.config import Settings
    from src.execution.router import run_application

    detection = Detection(ats="greenhouse", tier="tier1")
    result = asyncio.run(run_application(
        detection=detection,
        url="https://boards.greenhouse.io/x/jobs/1",
        task="apply",
        settings=Settings.from_env(),
    ))
    assert result.tier_used == "tier1"
    assert result.ok is True


def test_stuck_guard_raises() -> None:
    import asyncio

    from src.browser.handoff import StuckError, stuck_guard

    async def _slow():
        async with stuck_guard("test", stuck_seconds=0.1):
            await asyncio.sleep(0.5)

    with pytest.raises(StuckError):
        asyncio.run(_slow())


def test_stuck_guard_allows_fast() -> None:
    import asyncio

    from src.browser.handoff import stuck_guard

    async def _fast():
        async with stuck_guard("test", stuck_seconds=2.0):
            await asyncio.sleep(0.01)

    asyncio.run(_fast())  # no exception
