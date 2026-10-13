"""qa_log semantic search + stuck guard (no LLM)."""

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
    # Different phrasing, OPPOSITE polarity. Sensitive (visa) questions are
    # only reused on an exact match, so this must go to a human.
    m = lookup("Are you authorized to work in the US without sponsorship?")
    assert m.decision == "pause"
    assert m.answer is None


def test_qa_log_company_specific_answer_not_copied_across_companies() -> None:
    from src.profile.qa_log import lookup, store
    store("Why do you want to work at Acme?", "Because Acme builds X.", source="human",
          company="Acme")
    m = lookup("Why do you want to work at Acme?", company="Globex")
    assert m.decision != "reuse"


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


def test_stuck_guard_pause_stops_the_clock() -> None:
    """Waiting on a human (guard.paused()) must not count as being stuck."""
    import asyncio

    from src.browser.handoff import stuck_guard

    async def _waits_for_human():
        async with stuck_guard("test", stuck_seconds=0.3) as g:
            async with g.paused():
                await asyncio.sleep(0.6)
            await asyncio.sleep(0.05)

    asyncio.run(_waits_for_human())  # no StuckError


def test_stuck_guard_does_not_swallow_external_cancel() -> None:
    import asyncio

    from src.browser.handoff import stuck_guard

    async def _body():
        async with stuck_guard("test", stuck_seconds=5):
            await asyncio.sleep(5)

    async def _main():
        t = asyncio.create_task(_body())
        await asyncio.sleep(0.05)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    asyncio.run(_main())
