"""apply_to(url): the full end-to-end pipeline.

Flow (docs/SPEC.md §0, §6):
  1. Detect ATS + tier.
  2. Parse the job (Tier-1 adapter DOM parse, or Tier-2 fetch + LLM extract).
  3. Pre-flight checks (window, cooldown, daily cap, salary floor, sponsor).
  4. Ensure a portal account if the posting requires one.
  5. Select base resume (family route → cosine) → tailor (Gemini, validated) →
     render (LibreOffice) → build ApplicationPlan.
  6. Persist a queued application row.
  7. Telegram approval gate.
  8. Fill: Tier-1 deterministic adapter, or Tier-2 LLM loop. dry_run gates the
     final submit click. A stuck field escalates to a Tier-3 human handoff.
  9. Screenshot + status update.

The two execution tiers diverge only at parse (step 2) and fill (step 8);
steps 3-7 are shared via `_prepare` and `_approve`.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from src.ats.base import ApplicationPlan, ParsedJob
from src.ats.detector import Detection, adapter_for, route
from src.browser.handoff import StuckError, stuck_guard
from src.browser.harness import browser_session, screenshot
from src.company_research.scraper import fetch as fetch_company
from src.config import DATA_DIR, Settings
from src.db.models import Application
from src.db.session import get_session
from src.llm.client import GeminiClient
from src.orchestrator.preflight import company_role_hash
from src.orchestrator.preflight import run_all as preflight_all
from src.profile.loader import load as load_profile
from src.resume.embeddings import embed
from src.resume.renderer import RenderResult, render
from src.resume.selector import ResumeChoice, select
from src.resume.source import read_source
from src.resume.tailor import tailor
from src.resume.validator import ValidationResult
from src.util.time import utcnow

log = logging.getLogger(__name__)


@dataclass
class ApplyResult:
    ok: bool
    application_id: int | None
    reason: str
    plan: ApplicationPlan | None = None


@dataclass
class _Prep:
    """Everything produced by the tier-agnostic middle of the pipeline."""

    app_id: int
    job: ParsedJob
    plan: ApplicationPlan
    choice: ResumeChoice
    rendered: RenderResult
    validation: ValidationResult


async def apply_to(
    url: str,
    *,
    settings: Settings,
    telegram=None,  # optional TelegramBot for approval + handoff
) -> ApplyResult:
    """End-to-end application flow. Always dry-run when settings.dry_run is True."""
    log.info("apply_to: %s (dry_run=%s)", url, settings.dry_run)

    detection = route(url)
    log.info("detected ats=%s tier=%s", detection.ats, detection.tier)

    if detection.tier == "tier3":
        return ApplyResult(
            ok=False, application_id=None,
            reason=f"{detection.ats} is Tier-3 (manual takeover only). "
                   f"Open it yourself and use /done when finished.",
        )

    try:
        profile = load_profile()
    except Exception as e:
        return ApplyResult(ok=False, application_id=None, reason=f"profile load failed: {e}")

    if detection.tier == "tier1":
        return await _apply_tier1(url, detection, settings, profile, telegram)
    return await _apply_tier2(url, detection, settings, profile, telegram)


# --- Tier-1: deterministic Playwright adapter -------------------------------


async def _apply_tier1(url, detection, settings, profile, telegram) -> ApplyResult:
    adapter_cls = adapter_for(detection)
    if adapter_cls is None:
        # Shouldn't happen (detector said tier1) but degrade to Tier-2 rather
        # than dead-end.
        log.warning("no tier-1 adapter for %s; falling back to tier-2", detection.ats)
        return await _apply_tier2(url, detection, settings, profile, telegram)

    async with browser_session(headless=False) as (_ctx, page):
        adapter = adapter_cls()
        job = await adapter.parse_job(page, url)

        prep_or_err = await _prepare(job, url, detection, settings, profile, telegram)
        if isinstance(prep_or_err, ApplyResult):
            return prep_or_err
        prep = prep_or_err

        if not await _approve(telegram, prep):
            return _mark_rejected(prep.app_id, prep.plan)

        # Fill via the deterministic adapter, guarded against a stuck field.
        # `ask` lets the adapter learn answers to unknown fields (qa_log + HITL).
        ask = _make_ask(prep.app_id, telegram)
        try:
            async with stuck_guard(f"{detection.ats}.fill", stuck_seconds=90.0):
                await adapter.fill(page, prep.plan, dry_run=settings.dry_run, ask=ask)
        except StuckError as e:
            return await _handoff(prep.app_id, page, telegram, str(e), prep.plan)
        except Exception as e:
            log.error("adapter fill failed: %s", e)
            return ApplyResult(
                ok=False, application_id=prep.app_id,
                reason=f"fill failed: {e}", plan=prep.plan,
            )

        shot = await screenshot(
            page, DATA_DIR / "screenshots" / f"{prep.app_id}_{prep.rendered.uuid}.png",
        )
        return _finalize(prep, settings, str(shot))


# --- Tier-2: vision/LLM-driven loop -----------------------------------------


async def _apply_tier2(url, detection, settings, profile, telegram) -> ApplyResult:
    if not settings.gemini_configured():
        return ApplyResult(
            ok=False, application_id=None,
            reason=f"{detection.ats} needs the Tier-2 LLM loop, but GEMINI_API_KEY "
                   f"is not set. Add it to .env or apply via a Tier-1 ATS.",
        )

    # Parse the JD without an adapter: fetch page text, LLM-extract company/role.
    client = GeminiClient(settings)
    job = await _parse_job_llm(url, client)

    prep_or_err = await _prepare(job, url, detection, settings, profile, telegram, client=client)
    if isinstance(prep_or_err, ApplyResult):
        return prep_or_err
    prep = prep_or_err

    if not await _approve(telegram, prep):
        return _mark_rejected(prep.app_id, prep.plan)

    # Hand the tailored plan to the LLM browser loop. It opens its own browser
    # session and drives the form. Low confidence surfaces as a handoff.
    from src.ats.llm_fallback import apply_with_llm

    try:
        result = await apply_with_llm(
            url=url, plan=prep.plan, settings=settings, dry_run=settings.dry_run,
        )
    except Exception as e:
        log.error("tier-2 fill failed: %s", e)
        return ApplyResult(
            ok=False, application_id=prep.app_id,
            reason=f"tier-2 fill failed: {e}", plan=prep.plan,
        )

    status = result.get("status")
    if status == "low_confidence":
        return await _handoff(
            prep.app_id, None, telegram,
            "Tier-2 hit low confidence (captcha or ambiguous form)", prep.plan,
        )
    return _finalize(prep, settings, screenshot_path=None)


# --- shared middle ----------------------------------------------------------


async def _prepare(
    job, url, detection, settings, profile, telegram, *, client=None,
) -> _Prep | ApplyResult:
    """Preflight → account → research → select → tailor → render → plan → persist."""
    pre = preflight_all(
        company=job.company,
        role=job.role,
        desired_base_min=profile.compensation.desired_base_min,
        posting_max=job.salary_max,
    )
    if not pre.ok:
        log.warning("preflight blocked: %s", pre.reason)
        return ApplyResult(ok=False, application_id=None, reason=pre.reason)

    if client is None:
        if not settings.gemini_configured():
            return ApplyResult(
                ok=False, application_id=None,
                reason="GEMINI_API_KEY not set — cannot tailor a resume.",
            )
        client = GeminiClient(settings)

    # Company research is best-effort and only over the company's own site
    # (never a wrong guess). Currently feeds essay/fit context in later phases.
    company_facts = await _research(job, detection)

    # Resume selection (two-stage) + tailoring + validation.
    try:
        jd_emb = embed(job.description_md) if job.description_md else None
    except Exception:
        jd_emb = None
    try:
        choice = select(job.description_md, jd_embedding=jd_emb, embed_fn=embed)
    except FileNotFoundError as e:
        return ApplyResult(ok=False, application_id=None, reason=f"no resume to tailor: {e}")
    source_text = read_source(choice.md_path)

    tr = await tailor(
        jd=job.description_md,
        source_md=source_text,
        company=job.company,
        role=job.role,
        client=client,
        profile_known_text=_profile_known_text(profile),
    )
    if not tr.ok:
        return ApplyResult(
            ok=False, application_id=None,
            reason=f"validator REJECTED tailored output after {tr.attempts} attempts: "
                   f"{tr.validation.reason}",
        )

    rendered = render(tr.tailored_md, variant=choice.variant, company=job.company, role=job.role)
    plan = _build_plan(profile, rendered.pdf_path, company_facts, job)

    # Persist the queued application (need app_id for account signup + approval).
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    with get_session() as s:
        row = Application(
            url=url, url_hash=url_hash,
            company=job.company, role_title=job.role,
            ats=detection.ats, tier_used=detection.tier,
            resume_pdf=str(rendered.pdf_path), resume_uuid=rendered.uuid,
            status="tailored",
            notes=f"plan_hash={company_role_hash(job.company, job.role)}",
        )
        s.add(row)
        s.commit()
        app_id = row.id

    # Ensure a portal account if the posting requires sign-in (best-effort).
    if job.requires_account:
        acct_err = await _ensure_account(url, app_id, settings)
        if acct_err is not None:
            return ApplyResult(ok=False, application_id=app_id, reason=acct_err, plan=plan)

    return _Prep(
        app_id=app_id, job=job, plan=plan, choice=choice,
        rendered=rendered, validation=tr.validation,
    )


async def _approve(telegram, prep: _Prep) -> bool:
    if telegram is None:
        return True  # CLI / headless: no gate (still dry-run by default)
    from src.telegram_bot.cards import approval_card

    await telegram.send_approval(
        approval_card(prep.app_id, prep.job, prep.choice.variant, prep.rendered, prep.validation),
    )
    return await telegram.wait_for_approval(prep.app_id, timeout_seconds=600)


def _finalize(prep: _Prep, settings, screenshot_path: str | None) -> ApplyResult:
    with get_session() as s:
        r = s.get(Application, prep.app_id)
        if r:
            if settings.dry_run:
                r.status = "tailored"
                r.notes = (r.notes or "") + " | dry-run, no submit click"
            else:
                r.status = "submitted"
                r.applied_at = utcnow()
            if screenshot_path:
                r.screenshot_path = screenshot_path
            s.commit()
    return ApplyResult(
        ok=True, application_id=prep.app_id,
        reason="dry-run complete" if settings.dry_run else "submitted",
        plan=prep.plan,
    )


def _mark_rejected(app_id: int, plan: ApplicationPlan) -> ApplyResult:
    with get_session() as s:
        r = s.get(Application, app_id)
        if r:
            r.status = "rejected"
            r.notes = (r.notes or "") + " | user declined approval"
            s.commit()
    return ApplyResult(ok=False, application_id=app_id, reason="user declined approval", plan=plan)


async def _handoff(app_id, page, telegram, reason, plan) -> ApplyResult:
    """Escalate to a Tier-3 human takeover."""
    log.warning("handoff for app #%s: %s", app_id, reason)
    if telegram is not None and page is not None:
        try:
            from src.execution.tier3_handoff import request_handoff
            await request_handoff(
                application_id=app_id, page=page, telegram=telegram, reason=reason,
            )
        except Exception as e:
            log.error("handoff notification failed: %s", e)
    else:
        with get_session() as s:
            r = s.get(Application, app_id)
            if r:
                r.status = "handoff"
                r.notes = (r.notes or "") + f" | handoff: {reason}"
                s.commit()
    return ApplyResult(
        ok=False, application_id=app_id,
        reason=f"escalated to manual takeover: {reason}", plan=plan,
    )


# --- helpers ----------------------------------------------------------------


async def _research(job: ParsedJob, detection: Detection) -> str:
    """Fetch company facts from the company's OWN site, if we can identify it.

    We never guess `<company>.com` — that's wrong more often than right. When
    the posting lives on the company's own careers page (Tier-2 / unknown ATS),
    its host is the company domain. For ATS aggregators (Greenhouse, Lever, …)
    we skip rather than guess. Phase B adds LLM domain resolution.
    """
    host = urlparse(job.apply_url or "").netloc.lower()
    aggregator = any(
        a in host
        for a in ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
                  "smartrecruiters.com", "myworkdayjobs.com", "icims.com", "linkedin.com")
    )
    if not host or aggregator:
        return ""
    try:
        facts = await fetch_company(f"https://{host}")
        return facts.as_prompt_block()
    except Exception as e:
        log.info("company research skipped: %s", e)
        return ""


async def _parse_job_llm(url: str, client: GeminiClient) -> ParsedJob:
    """Tier-2 JD parse: fetch the page text and LLM-extract company + role."""
    import json

    import httpx

    text = ""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as http:
            r = await http.get(url, headers={"User-Agent": "Mozilla/5.0 apply-agent"})
            if r.status_code < 400:
                from src.company_research.scraper import _html_to_text
                text = _html_to_text(r.text)[:6000]
    except Exception as e:
        log.info("tier-2 JD fetch failed (%s); relying on URL only", e)

    prompt = (
        "Extract the hiring company and the job title from this posting. "
        'Return JSON only: {"company":"...","role":"..."}. If unknown, use "Unknown".\n\n'
        f"URL: {url}\n\n{text}"
    )
    company, role = "Unknown Company", "Unknown Role"
    try:
        out = await client.generate(prompt, temperature=0.0, json_mode=True, max_output_tokens=200)
        d = json.loads(out)
        company = (d.get("company") or company).strip()
        role = (d.get("role") or role).strip()
    except Exception as e:
        log.warning("tier-2 JD extract failed: %s", e)

    return ParsedJob(company=company, role=role, description_md=text, apply_url=url,
                     requires_account=False)


async def _ensure_account(url: str, app_id: int, settings: Settings) -> str | None:
    """Create + verify a portal account if needed. Returns an error string or None."""
    if not settings.master_key_path.exists():
        return ("posting requires an account, but no vault master key exists "
                "(run `make keygen`). Apply manually or set up the vault.")
    try:
        from src.accounts.signup import ensure_account
        from src.accounts.vault import Vault
        vault = Vault.open(settings.master_key_path)
        await ensure_account(portal_url=url, application_id=app_id, vault=vault, settings=settings)
        return None
    except Exception as e:
        log.error("account signup failed: %s", e)
        return f"account signup failed: {e}"


def _make_ask(app_id: int, telegram):
    """Build the adapter `ask` callback: learned-answer lookup → HITL pause → learn.

    1. Check the semantic qa_log. On a high-confidence match (reuse) or a
       mid-band match (rephrase), return the stored answer.
    2. Otherwise pause and ask the human over Telegram.
    3. Persist a human answer to qa_log (source=human) AND log a training_runs
       row, so the same question is answered automatically next time. This is
       the learning loop — the reason the agent gets smarter with use.
    """
    async def ask(question: str) -> str | None:
        from src.profile.qa_log import lookup, store

        try:
            m = lookup(question)
        except Exception as e:
            log.debug("qa_log lookup failed: %s", e)
            m = None
        if m is not None and m.decision in ("reuse", "rephrase") and m.answer:
            log.info("qa_log %s (score=%.2f) for %r", m.decision, m.score, question[:60])
            return m.answer

        if telegram is None:
            return None  # headless: leave unknown fields blank

        answer = await telegram.ask_question(app_id, question)
        if answer:
            try:
                store(question, answer, source="human", confidence=1.0)
                _record_intervention(app_id, question, answer)
            except Exception as e:
                log.warning("failed to persist learned answer: %s", e)
        return answer

    return ask


def _record_intervention(app_id: int, question: str, answer: str) -> None:
    """Write a training_runs row for a human intervention (batch analyzer input)."""
    from src.db.models import TrainingRun
    with get_session() as s:
        s.add(TrainingRun(
            application_id=app_id,
            question=question,
            agent_action="pause",
            human_action=answer,
            intervened=True,
        ))
        s.commit()


def _profile_known_text(profile) -> str:
    """Flatten profile fields into a string the validator can reference."""
    parts = [
        profile.identity.legal_name,
        profile.identity.email,
        profile.identity.location.city,
        profile.identity.location.state,
        profile.work_authorization.current_status,
    ]
    for e in profile.education:
        parts.extend([e.degree, e.institution, str(e.grad_year)])
    return " ".join(p for p in parts if p)


def _split_name(legal_name: str) -> tuple[str, str]:
    """First + last name. Uses first and LAST tokens so middle names don't
    pollute the surname ("Mary Anne Smith" → first=Mary, last=Smith).
    Mononyms use the same token for both."""
    tokens = legal_name.split()
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], tokens[0]
    return tokens[0], tokens[-1]


def _build_plan(profile, resume_pdf, company_facts, job) -> ApplicationPlan:
    first, last = _split_name(profile.identity.legal_name)
    return ApplicationPlan(
        resume_pdf=resume_pdf,
        cover_letter_md=None,  # cover-letter generation not enabled by default
        answers={
            "first_name": first,
            "last_name": last,
            "email": str(profile.identity.email),
            "phone": profile.identity.phone,
            "linkedin": str(profile.identity.linkedin) if profile.identity.linkedin else "",
            "github": str(profile.identity.github) if profile.identity.github else "",
            "portfolio": str(profile.identity.portfolio) if profile.identity.portfolio else "",
            "how_did_you_hear": profile.background.how_did_you_hear_default,
            "sponsorship_response": (
                "Yes — I'll require employment sponsorship now or in the future."
                if profile.work_authorization.requires_sponsorship else
                "No — I do not require sponsorship."
            ),
            "salary_expectation": (
                f"${profile.compensation.desired_base_target:,} base "
                f"(open ${profile.compensation.desired_base_min:,}+)"
            ),
        },
        essays={},
        notes=f"company_facts_len={len(company_facts)}",
    )
