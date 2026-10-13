"""End-to-end wiring tests for the orchestrator.

These fake the heavy boundaries (browser, LLM, render) and assert that
`apply_to` threads its pieces together AND holds the safety invariants:
dry-run never submits, a live submit needs an approval, no-Telegram fails
closed, a re-apply reuses the row, Tier-2 routing, HITL learning, Tier-3.
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


def _settings(*, dry_run: bool = True) -> Settings:
    s = Settings.from_env()
    s.gemini_api_key = "test-key"  # so gemini_configured() is True
    s.dry_run = dry_run
    s.no_telegram = True
    return s


class _FakeGeminiClient:
    def __init__(self, settings, limiter=None):
        pass

    async def generate(self, prompt, **_kw):
        return '{"company":"Acme","role":"Engineer"}'


class _FakeTelegram:
    """Duck-typed TelegramBot with a 'live' app and a scripted approval."""

    def __init__(self, decision: str = "approve", answer: str | None = "answer") -> None:
        self._app = object()
        self.decision = decision
        self.answer = answer
        self.cards: list = []
        self.photos: list = []
        self.questions: list = []

    async def send_card(self, card):
        self.cards.append(card)

    async def send_html(self, text):
        self.cards.append(text)

    async def send_photo(self, path, caption=""):
        self.photos.append(path)

    async def wait_for_approval(self, app_id, **_k):
        return self.decision

    async def ask_question(self, app_id, question, **_k):
        self.questions.append(question)
        return self.answer

    async def wait_for_done(self, app_id, **_k):
        return "timeout"

    def abort_requested(self, _app_id):
        return False

    def takeover_requested(self, _app_id):
        return False


def _patch_pipeline_seams(monkeypatch, *, tmp_path, adapter_cls=None):
    """Fake the expensive boundaries so apply_to's wiring can be exercised."""
    import src.orchestrator.pipeline as P
    from src.orchestrator.preflight import PreflightDecision

    monkeypatch.setattr("src.profile.loader.load", lambda: _fake_profile())
    monkeypatch.setattr(P, "preflight_all", lambda **_k: PreflightDecision.passing())
    monkeypatch.setattr(P, "check_submit_gates", lambda: PreflightDecision.passing())
    monkeypatch.setattr("src.llm.client.GeminiClient", _FakeGeminiClient)
    monkeypatch.setattr("src.resume.embeddings.embed", lambda _t: None)
    monkeypatch.setattr(
        P, "select_resume",
        lambda *a, **k: ResumeChoice(
            variant="master", md_path=tmp_path / "r.md", docx_path=tmp_path / "r.docx", score=1.0,
        ),
    )
    monkeypatch.setattr(P, "read_source", lambda _p: "- Built a thing.\n- Led a team.")

    async def _fake_tailor(**_k):
        return TailorResult(
            ok=True, tailored_md="- Built a similar thing.\n- Led the team.", attempts=1,
            validation=ValidationResult(ok=True, reason="ok"),
        )
    monkeypatch.setattr("src.resume.tailor.tailor", _fake_tailor)

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


# --- rate limiter singleton ---------------------------------------------------


def test_rate_limiter_is_process_singleton() -> None:
    from src.llm.rate_limiter import get_rate_limiter
    assert get_rate_limiter() is get_rate_limiter()


def test_client_defaults_to_shared_limiter(monkeypatch) -> None:
    # Two GeminiClients with no explicit limiter must share the singleton, so
    # RPD/RPM accounting is global. Avoid the real SDK client.
    import src.llm.client as C
    monkeypatch.setattr("google.genai.Client", lambda **_k: object())
    s = _settings()
    a, b = C.GeminiClient(s), C.GeminiClient(s)
    assert a._limiter is b._limiter


# --- name split ----------------------------------------------------------------


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


def test_plan_has_yes_no_work_authorization() -> None:
    from pathlib import Path

    from src.orchestrator.pipeline import _build_plan
    plan = _build_plan(_fake_profile(), Path("x.pdf"), ParsedJob(company="A", role="B"))
    assert plan.answers["authorized_us"] == "Yes"
    assert plan.answers["requires_sponsorship"] == "No"


# --- HITL learning ---------------------------------------------------------------


def _asker(telegram=None):
    from src.orchestrator.pipeline import _Asker
    return _Asker(1, telegram, company="Acme", client=None, profile_text="")


async def test_asker_reuses_learned_answer() -> None:
    from src.profile.qa_log import store

    store("How did you hear about this role?", "From the company careers page.", source="human")
    ans = await _asker()("How did you hear about this role?")
    assert ans == "From the company careers page."


async def test_asker_never_reuses_sensitive_near_match() -> None:
    """'Require sponsorship?' and 'work WITHOUT sponsorship?' embed alike but have
    opposite answers — a sensitive near-match must go to a human, not be reused."""
    from src.profile.qa_log import store

    store("Will you now or in the future require visa sponsorship?", "No", source="human")
    tg = _FakeTelegram(answer="Yes")
    ans = await _asker(tg)("Are you able to work in the US without visa sponsorship?")
    assert ans == "Yes"
    assert tg.questions, "sensitive question should have been asked, not reused"


async def test_asker_pauses_and_learns() -> None:
    """No prior answer + a human reply → answer used, stored, and logged."""
    from sqlalchemy import select

    from src.db.models import Application, QALog, TrainingRun
    from src.db.session import get_session
    from src.orchestrator.pipeline import _Asker
    with get_session() as s:
        s.add(Application(id=7, url="https://x.test/j/7", url_hash="h7", company="Acme",
                          role_title="Eng", status="tailored"))
        s.commit()

    ask = _Asker(7, _FakeTelegram(answer="Ten years"), company="Acme", client=None,
                 profile_text="")
    ans = await ask("How many years of experience do you have?")
    assert ans == "Ten years"

    with get_session() as s:
        qa = list(s.scalars(select(QALog)))
        tr = list(s.scalars(select(TrainingRun)))
    assert any(q.answer_text == "Ten years" and q.company == "Acme" for q in qa)
    assert any(t.intervened and t.application_id == 7 for t in tr), "no training_runs row"


# --- end-to-end wiring --------------------------------------------------------------


class _FakeTier1Adapter:
    calls: typing.ClassVar[list] = []
    submits: typing.ClassVar[int] = 0

    async def parse_job(self, page, url):
        return ParsedJob(company="Acme", role="Engineer", description_md="python jd", apply_url=url)

    async def fill(self, page, plan, *, ask=None):
        _FakeTier1Adapter.calls.append({"ask_wired": ask is not None})

    async def submit(self, page):
        _FakeTier1Adapter.submits += 1
        return True


def _reset_adapter():
    _FakeTier1Adapter.calls = []
    _FakeTier1Adapter.submits = 0


def _row(app_id):
    from src.db.models import Application
    from src.db.session import get_session
    with get_session() as s:
        return s.get(Application, app_id)


GH = "https://boards.greenhouse.io/acme/jobs/123"


async def test_dry_run_fills_but_never_submits(monkeypatch, tmp_path) -> None:
    from src.orchestrator.pipeline import apply_to

    _reset_adapter()
    _patch_pipeline_seams(monkeypatch, tmp_path=tmp_path, adapter_cls=_FakeTier1Adapter)
    tg = _FakeTelegram(decision="approve")

    result = await apply_to(GH, settings=_settings(), telegram=tg)
    assert result.ok, result.reason
    assert _FakeTier1Adapter.calls == [{"ask_wired": True}]
    assert _FakeTier1Adapter.submits == 0, "dry run clicked submit (safety!)"
    assert _row(result.application_id).status == "tailored"
    assert tg.photos, "approval must show the filled-form screenshot"


async def test_dry_run_without_telegram_still_never_submits(monkeypatch, tmp_path) -> None:
    from src.orchestrator.pipeline import apply_to

    _reset_adapter()
    _patch_pipeline_seams(monkeypatch, tmp_path=tmp_path, adapter_cls=_FakeTier1Adapter)
    result = await apply_to(GH, settings=_settings(), telegram=None)
    assert result.ok, result.reason
    assert _FakeTier1Adapter.submits == 0


async def test_live_submit_requires_and_follows_approval(monkeypatch, tmp_path) -> None:
    from src.orchestrator.pipeline import apply_to

    _reset_adapter()
    _patch_pipeline_seams(monkeypatch, tmp_path=tmp_path, adapter_cls=_FakeTier1Adapter)
    result = await apply_to(GH, settings=_settings(dry_run=False),
                            telegram=_FakeTelegram(decision="approve"))
    assert result.ok, result.reason
    assert _FakeTier1Adapter.submits == 1
    row = _row(result.application_id)
    assert row.status == "submitted" and row.applied_at is not None


async def test_live_submit_rejected_by_human(monkeypatch, tmp_path) -> None:
    from src.orchestrator.pipeline import apply_to

    _reset_adapter()
    _patch_pipeline_seams(monkeypatch, tmp_path=tmp_path, adapter_cls=_FakeTier1Adapter)
    result = await apply_to(GH, settings=_settings(dry_run=False),
                            telegram=_FakeTelegram(decision="reject"))
    assert not result.ok
    assert _FakeTier1Adapter.submits == 0
    assert _row(result.application_id).status == "rejected"


async def test_live_without_telegram_fails_closed(monkeypatch, tmp_path) -> None:
    from src.orchestrator.pipeline import apply_to

    _reset_adapter()
    _patch_pipeline_seams(monkeypatch, tmp_path=tmp_path, adapter_cls=_FakeTier1Adapter)
    result = await apply_to(GH, settings=_settings(dry_run=False), telegram=None)
    assert not result.ok
    assert "telegram" in result.reason.lower()
    assert _FakeTier1Adapter.calls == [] and _FakeTier1Adapter.submits == 0


async def test_submit_gate_rechecked_before_click(monkeypatch, tmp_path) -> None:
    """Approval can take minutes: window/cap are re-checked right before Submit."""
    import src.orchestrator.pipeline as P
    from src.orchestrator.pipeline import apply_to
    from src.orchestrator.preflight import PreflightDecision

    _reset_adapter()
    _patch_pipeline_seams(monkeypatch, tmp_path=tmp_path, adapter_cls=_FakeTier1Adapter)
    monkeypatch.setattr(P, "check_submit_gates",
                        lambda: PreflightDecision.deferred("outside submission window"))
    result = await apply_to(GH, settings=_settings(dry_run=False),
                            telegram=_FakeTelegram(decision="approve"))
    assert not result.ok and "window" in result.reason
    assert _FakeTier1Adapter.submits == 0
    assert _row(result.application_id).status == "deferred"


async def test_reapply_same_url_reuses_row(monkeypatch, tmp_path) -> None:
    """Dry run, then again: no UNIQUE(url_hash) crash, same application row."""
    from src.orchestrator.pipeline import apply_to

    _reset_adapter()
    _patch_pipeline_seams(monkeypatch, tmp_path=tmp_path, adapter_cls=_FakeTier1Adapter)
    r1 = await apply_to(GH, settings=_settings(), telegram=None)
    r2 = await apply_to(GH, settings=_settings(), telegram=None)
    assert r1.ok and r2.ok
    assert r1.application_id == r2.application_id


async def test_already_submitted_url_is_refused(monkeypatch, tmp_path) -> None:
    from src.orchestrator.pipeline import apply_to

    _reset_adapter()
    _patch_pipeline_seams(monkeypatch, tmp_path=tmp_path, adapter_cls=_FakeTier1Adapter)
    r1 = await apply_to(GH, settings=_settings(dry_run=False), telegram=_FakeTelegram())
    assert r1.ok
    r2 = await apply_to(GH, settings=_settings(dry_run=False), telegram=_FakeTelegram())
    assert not r2.ok and "already applied" in r2.reason
    assert _FakeTier1Adapter.submits == 1


async def test_apply_to_tier2_routes_to_llm(monkeypatch, tmp_path) -> None:
    """A non-Tier-1 ATS reaches the Tier-2 LLM loop; 'ready' + dry-run → ok, no submit."""
    import src.ats.llm_fallback as LF
    import src.orchestrator.pipeline as P
    from src.orchestrator.pipeline import apply_to

    _patch_pipeline_seams(monkeypatch, tmp_path=tmp_path)

    async def _fake_parse(url, client):
        return ParsedJob(company="Acme", role="Eng", description_md="jd", apply_url=url)
    monkeypatch.setattr(P, "_parse_job_llm", _fake_parse)

    seen = {}

    async def _fake_apply_with_llm(*, page, url, plan, settings, client=None):
        seen["url"] = url
        return {"status": "ready", "submit_selector": "button#submit"}
    monkeypatch.setattr(LF, "apply_with_llm", _fake_apply_with_llm)

    clicked = []

    async def _fake_submit(page, sel):
        clicked.append(sel)
        return True
    monkeypatch.setattr(P, "_submit_tier2", _fake_submit)

    result = await apply_to(
        "https://acme.wd1.myworkdayjobs.com/en-US/careers/job/123",
        settings=_settings(), telegram=None,
    )
    assert result.ok, result.reason
    assert seen.get("url", "").startswith("https://acme.wd1.myworkdayjobs.com")
    assert clicked == [], "Tier-2 dry run must not click submit"


async def test_tier2_unfinished_is_not_success(monkeypatch, tmp_path) -> None:
    """max_steps / anything but 'ready' must NOT be recorded as a success."""
    import src.ats.llm_fallback as LF
    import src.orchestrator.pipeline as P
    from src.orchestrator.pipeline import apply_to

    _patch_pipeline_seams(monkeypatch, tmp_path=tmp_path)

    async def _fake_parse(url, client):
        return ParsedJob(company="Acme", role="Eng", description_md="jd", apply_url=url)
    monkeypatch.setattr(P, "_parse_job_llm", _fake_parse)

    async def _fake_apply_with_llm(**_k):
        return {"status": "max_steps"}
    monkeypatch.setattr(LF, "apply_with_llm", _fake_apply_with_llm)

    result = await apply_to(
        "https://acme.wd1.myworkdayjobs.com/en-US/careers/job/9",
        settings=_settings(), telegram=None,
    )
    assert not result.ok
    assert _row(result.application_id).status == "handoff"


async def test_apply_to_linkedin_is_tier3_manual() -> None:
    """LinkedIn never auto-applies — every URL shape returns a manual-only message."""
    from src.orchestrator.pipeline import apply_to
    for url in ("https://www.linkedin.com/jobs/view/123",
                "https://www.linkedin.com/comm/jobs/view/123",
                "https://lnkd.in/abc"):
        result = await apply_to(url, settings=_settings(), telegram=None)
        assert result.ok is False
        assert "manual" in result.reason.lower(), url
