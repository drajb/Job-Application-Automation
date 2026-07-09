"""End-to-end wiring tests for the orchestrator (the M0 root-cause coverage).

These fake the heavy boundaries (browser, LLM, render) and assert that
`apply_to` actually threads its pieces together — the integration gaps that
unit tests missed: shared rate limiter, Tier-2 routing, HITL learning, dry-run
propagation, and Tier-3 handoff.
"""

from __future__ import annotations

import typing
from contextlib import asynccontextmanager

import pytest

from src.ats.base import ParsedJob
from src.config import Settings
from src.profile.schema import (
    Background,
    Compensation,
    Demographics,
    Education,
    Essays,
    Identity,
    Location,
    Profile,
    WorkAuthorization,
)
from src.resume.selector import ResumeChoice
from src.resume.tailor import TailorResult
from src.resume.validator import ValidationResult


@pytest.fixture(autouse=True)
def _ephemeral_db(tmp_path, monkeypatch):
    db_path = tmp_path / "wiring.db"
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


def _fake_profile() -> Profile:
    return Profile(
        identity=Identity(
            legal_name="Jane Q Doe",
            email="jane.doe@example.com",
            phone="+1-555-555-0100",
            location=Location(city="Springfield", state="IL"),
        ),
        work_authorization=WorkAuthorization(
            authorized_us=True, requires_sponsorship=False, current_status="Citizen",
        ),
        demographics=Demographics(),
        compensation=Compensation(desired_base_min=150000, desired_base_target=180000),
        background=Background(),
        education=[Education(degree="B.S.", institution="State University", grad_year=2018)],
        essays=Essays(),
    )


def _settings() -> Settings:
    s = Settings.from_env()
    s.gemini_api_key = "test-key"  # so gemini_configured() is True
    s.dry_run = True
    s.no_telegram = True
    return s


class _FakeGeminiClient:
    def __init__(self, settings, limiter=None):
        pass

    async def generate(self, prompt, **_kw):
        return '{"company":"Acme","role":"Engineer"}'


def _patch_pipeline_seams(monkeypatch, *, tmp_path, adapter_cls=None):
    """Fake the expensive boundaries so apply_to's wiring can be exercised."""
    import src.orchestrator.pipeline as P
    from src.orchestrator.preflight import PreflightDecision

    monkeypatch.setattr(P, "load_profile", lambda: _fake_profile())
    monkeypatch.setattr(P, "preflight_all", lambda **_k: PreflightDecision.passing())
    monkeypatch.setattr(P, "GeminiClient", _FakeGeminiClient)
    monkeypatch.setattr(P, "embed", lambda _t: None)
    monkeypatch.setattr(
        P, "select",
        lambda *a, **k: ResumeChoice(
            variant="master", md_path=tmp_path / "r.md", docx_path=tmp_path / "r.docx", score=1.0,
        ),
    )
    monkeypatch.setattr(P, "read_source", lambda _p: "resume source text")

    async def _fake_tailor(**_k):
        return TailorResult(
            ok=True, tailored_md="# tailored", attempts=1,
            validation=ValidationResult(ok=True, reason="ok"),
        )
    monkeypatch.setattr(P, "tailor", _fake_tailor)

    pdf = tmp_path / "out.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    from src.resume.renderer import RenderResult
    monkeypatch.setattr(
        P, "render",
        lambda *a, **k: RenderResult(uuid="uuid123", docx_path=tmp_path / "o.docx", pdf_path=pdf),
    )

    async def _fake_screenshot(page, path):
        return path
    monkeypatch.setattr(P, "screenshot", _fake_screenshot)

    @asynccontextmanager
    async def _fake_session(*, headless=False):
        yield (None, object())
    monkeypatch.setattr(P, "browser_session", _fake_session)

    if adapter_cls is not None:
        monkeypatch.setattr(P, "adapter_for", lambda _d: adapter_cls)


# --- M0.1: rate limiter singleton -------------------------------------------


def test_rate_limiter_is_process_singleton() -> None:
    from src.llm.rate_limiter import get_rate_limiter
    assert get_rate_limiter() is get_rate_limiter()


def test_client_defaults_to_shared_limiter(monkeypatch) -> None:
    # Two GeminiClients with no explicit limiter must share the singleton, so
    # RPD/RPM accounting is global. We avoid real genai by patching configure.
    import src.llm.client as C
    monkeypatch.setattr(C.genai, "configure", lambda **_k: None)
    monkeypatch.setattr(C.genai, "GenerativeModel", lambda *_a, **_k: object())
    s = _settings()
    a, b = C.GeminiClient(s), C.GeminiClient(s)
    assert a._limiter is b._limiter


# --- M0.5: name split + research honesty ------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Jane Doe", ("Jane", "Doe")),
        ("Mary Anne Smith", ("Mary", "Smith")),
        ("Cher", ("Cher", "Cher")),
        ("", ("", "")),
    ],
)
def test_split_name(name, expected) -> None:
    from src.orchestrator.pipeline import _split_name
    assert _split_name(name) == expected


async def test_research_skips_ats_aggregators(monkeypatch) -> None:
    import src.orchestrator.pipeline as P
    from src.ats.detector import Detection

    called = False

    async def _boom(_url):
        nonlocal called
        called = True
        raise AssertionError("should not fetch for an aggregator host")

    monkeypatch.setattr(P, "fetch_company", _boom)
    job = ParsedJob(company="Acme", role="Eng",
                    apply_url="https://boards.greenhouse.io/acme/jobs/1")
    out = await P._research(job, Detection(ats="greenhouse", tier="tier1"))
    assert out == "" and called is False


# --- M0.3: HITL learning ----------------------------------------------------


async def test_make_ask_reuses_learned_answer() -> None:
    """A learned answer is returned without needing a human."""
    from src.orchestrator.pipeline import _make_ask
    from src.profile.qa_log import store

    store("Will you require visa sponsorship?", "No, I am a citizen.", source="human")
    ask = _make_ask(app_id=1, telegram=None)
    ans = await ask("Will you require visa sponsorship?")
    assert ans == "No, I am a citizen."


async def test_make_ask_pauses_and_learns() -> None:
    """No prior answer + a human reply → answer used, stored, and logged."""
    from sqlalchemy import select

    from src.db.models import QALog, TrainingRun
    from src.db.session import get_session
    from src.orchestrator.pipeline import _make_ask

    class _FakeTelegram:
        async def ask_question(self, app_id, question, **_k):
            return "42 years of experience"

    ask = _make_ask(app_id=7, telegram=_FakeTelegram())
    ans = await ask("How many years of experience do you have?")
    assert ans == "42 years of experience"

    with get_session() as s:
        qa = list(s.scalars(select(QALog)))
        tr = list(s.scalars(select(TrainingRun)))
    assert any("42 years" in q.answer_text for q in qa), "answer not stored to qa_log"
    assert any(t.intervened and t.application_id == 7 for t in tr), "no training_runs row"


# --- end-to-end wiring (G1-G5 root cause) -----------------------------------


class _FakeTier1Adapter:
    calls: typing.ClassVar[list] = []

    async def parse_job(self, page, url):
        return ParsedJob(company="Acme", role="Engineer", description_md="jd body", apply_url=url)

    async def fill(self, page, plan, *, dry_run, ask=None):
        _FakeTier1Adapter.calls.append({"dry_run": dry_run, "ask_wired": ask is not None})


async def test_apply_to_tier1_end_to_end(monkeypatch, tmp_path) -> None:
    """apply_to threads parse→prepare→approve→fill→finalize and passes dry_run + ask."""
    from src.orchestrator.pipeline import apply_to

    _FakeTier1Adapter.calls = []
    _patch_pipeline_seams(monkeypatch, tmp_path=tmp_path, adapter_cls=_FakeTier1Adapter)

    result = await apply_to(
        "https://boards.greenhouse.io/acme/jobs/123", settings=_settings(), telegram=None,
    )
    assert result.ok, result.reason
    assert result.application_id is not None
    assert len(_FakeTier1Adapter.calls) == 1
    call = _FakeTier1Adapter.calls[0]
    assert call["dry_run"] is True, "dry_run not propagated to adapter (safety!)"
    assert call["ask_wired"] is True, "ask callback not wired (HITL learning dead)"

    # Persisted, and dry-run leaves status 'tailored' (never 'submitted').
    from src.db.models import Application
    from src.db.session import get_session
    with get_session() as s:
        row = s.get(Application, result.application_id)
    assert row is not None and row.status == "tailored"


async def test_apply_to_tier2_routes_to_llm(monkeypatch, tmp_path) -> None:
    """A non-Tier-1 ATS reaches the Tier-2 LLM loop instead of dead-ending (G2)."""
    import src.ats.llm_fallback as LF
    import src.orchestrator.pipeline as P
    from src.orchestrator.pipeline import apply_to

    _patch_pipeline_seams(monkeypatch, tmp_path=tmp_path)

    async def _fake_parse(url, client):
        return ParsedJob(company="Acme", role="Eng", description_md="jd", apply_url=url)
    monkeypatch.setattr(P, "_parse_job_llm", _fake_parse)

    seen = {}

    async def _fake_apply_with_llm(*, url, plan, settings, dry_run):
        seen["url"] = url
        seen["dry_run"] = dry_run
        return {"status": "done"}
    monkeypatch.setattr(LF, "apply_with_llm", _fake_apply_with_llm)

    result = await apply_to(
        "https://acme.wd1.myworkdayjobs.com/en-US/careers/job/123",
        settings=_settings(), telegram=None,
    )
    assert result.ok, result.reason
    assert seen.get("url", "").startswith("https://acme.wd1.myworkdayjobs.com")
    assert seen.get("dry_run") is True


async def test_apply_to_linkedin_is_tier3_manual() -> None:
    """LinkedIn never auto-applies — it returns a manual-takeover message (locked)."""
    from src.orchestrator.pipeline import apply_to
    result = await apply_to(
        "https://www.linkedin.com/jobs/view/123", settings=_settings(), telegram=None,
    )
    assert result.ok is False
    assert "manual" in result.reason.lower() or "tier-3" in result.reason.lower()
