"""apply_to(url): the full end-to-end pipeline.

Per docs/SPEC.md §0 and §6:
  1. Pre-flight checks (window, cooldown, daily cap, salary floor, sponsor).
  2. Open URL via routed execution tier.
  3. Detect ATS + parse job (Tier-1) OR LLM extracts JD (Tier-2).
  4. Select base resume (two-stage family → cosine).
  5. Tailor (Gemini Flash) + validate (sacred) + render (LibreOffice).
  6. Build ApplicationPlan (resume + cover + answers + essays).
  7. Persist queued application row.
  8. Telegram approval card → wait for ✅ Submit.
  9. On approval, run adapter.fill(..., dry_run=settings.dry_run).
 10. Log status, screenshot, response-tracking expectation row.

This module is the orchestrator. Each step is small + replaceable.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from src.ats.base import ApplicationPlan
from src.ats.detector import adapter_for, route
from src.browser.harness import browser_session, screenshot
from src.company_research.scraper import fetch as fetch_company
from src.config import DATA_DIR, Settings
from src.db.models import Application
from src.db.session import get_session
from src.llm.client import GeminiClient
from src.llm.rate_limiter import RateLimiter
from src.orchestrator.preflight import (
    company_role_hash,
)
from src.orchestrator.preflight import (
    run_all as preflight_all,
)
from src.profile.loader import load as load_profile
from src.resume.embeddings import embed
from src.resume.renderer import render
from src.resume.selector import select
from src.resume.source import read_source
from src.resume.tailor import tailor
from src.util.time import utcnow

log = logging.getLogger(__name__)


@dataclass
class ApplyResult:
    ok: bool
    application_id: int | None
    reason: str
    plan: ApplicationPlan | None = None


async def apply_to(
    url: str,
    *,
    settings: Settings,
    telegram=None,  # optional TelegramBot for approval flow
) -> ApplyResult:
    """End-to-end application flow. Always dry-run when settings.dry_run is True."""
    log.info("apply_to: %s (dry_run=%s)", url, settings.dry_run)

    # 1) Detect ATS + tier
    detection = route(url)
    log.info("detected ats=%s tier=%s", detection.ats, detection.tier)

    if detection.tier == "tier3":
        return ApplyResult(
            ok=False, application_id=None,
            reason=f"{detection.ats} requires manual takeover (Tier 3). Use /handoff.",
        )

    # 2) Load profile (needed for filling)
    try:
        profile = load_profile()
    except Exception as e:
        return ApplyResult(ok=False, application_id=None, reason=f"profile load failed: {e}")

    # 3) Open browser + parse job (tier-1 adapters)
    AdapterCls = adapter_for(detection)
    if AdapterCls is None:
        return ApplyResult(
            ok=False, application_id=None,
            reason=f"{detection.ats} has no tier-1 adapter yet (use tier-2 fallback).",
        )

    async with browser_session(headless=False) as (_ctx, page):
        adapter = AdapterCls()
        job = await adapter.parse_job(page, url)

        # 4) Pre-flight
        pre = preflight_all(
            company=job.company,
            role=job.role,
            desired_base_min=profile.compensation.desired_base_min,
            posting_max=job.salary_max,
        )
        if not pre.ok:
            log.warning("preflight blocked: %s", pre.reason)
            return ApplyResult(ok=False, application_id=None, reason=pre.reason)

        # 5) Company research (lightweight)
        company_facts = ""
        try:
            facts = await fetch_company(f"https://{job.company.lower().replace(' ', '')}.com")
            company_facts = facts.as_prompt_block()
        except Exception as e:
            log.info("company research skipped: %s", e)

        # 6) Resume selection (two-stage)
        try:
            jd_emb = embed(job.description_md) if job.description_md else None
        except Exception:
            jd_emb = None
        choice = select(job.description_md, jd_embedding=jd_emb, embed_fn=embed)
        source_text = read_source(choice.md_path)

        # 7) Tailor + validate (sacred)
        client = GeminiClient(settings, RateLimiter())
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

        # 8) Render
        rendered = render(
            tr.tailored_md, variant=choice.variant, company=job.company, role=job.role,
        )

        # 9) Build plan
        plan = _build_plan(profile, rendered.pdf_path, company_facts, job)

        # 10) Persist queued application
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        with get_session() as s:
            row = Application(
                url=url,
                url_hash=url_hash,
                company=job.company,
                role_title=job.role,
                ats=detection.ats,
                tier_used=detection.tier,
                resume_pdf=str(rendered.pdf_path),
                resume_uuid=rendered.uuid,
                status="tailored",
                notes=f"plan_hash={company_role_hash(job.company, job.role)}",
            )
            s.add(row)
            s.commit()
            app_id = row.id

        # 11) Telegram approval gate (inline Submit/Reject buttons)
        approved = True
        if telegram is not None:
            from src.telegram_bot.cards import approval_card
            await telegram.send_approval(
                approval_card(app_id, job, choice.variant, rendered, tr.validation),
            )
            approved = await telegram.wait_for_approval(app_id, timeout_seconds=600)

        if not approved:
            with get_session() as s:
                r = s.get(Application, app_id)
                if r:
                    r.status = "rejected"
                    r.notes = (r.notes or "") + " | user rejected"
                    s.commit()
            return ApplyResult(
                ok=False, application_id=app_id, reason="user declined approval", plan=plan,
            )

        # 12) Fill (dry-run unless explicitly off)
        try:
            await adapter.fill(page, plan, dry_run=settings.dry_run)
        except Exception as e:
            log.error("adapter fill failed: %s", e)
            return ApplyResult(
                ok=False, application_id=app_id, reason=f"fill failed: {e}", plan=plan,
            )

        # 13) Screenshot + status update
        shot = await screenshot(
            page, DATA_DIR / "screenshots" / f"{app_id}_{rendered.uuid}.png",
        )
        with get_session() as s:
            r = s.get(Application, app_id)
            if r:
                if settings.dry_run:
                    r.status = "tailored"
                    r.notes = (r.notes or "") + " | dry-run, no submit click"
                else:
                    r.status = "submitted"
                    r.applied_at = utcnow()
                r.screenshot_path = str(shot)
                s.commit()

        return ApplyResult(
            ok=True, application_id=app_id,
            reason="dry-run complete" if settings.dry_run else "submitted",
            plan=plan,
        )


# --- helpers --------------------------------------------------------------


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


def _build_plan(profile, resume_pdf, company_facts, job) -> ApplicationPlan:
    first, _, last = profile.identity.legal_name.partition(" ")
    if not last:
        last = first
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
