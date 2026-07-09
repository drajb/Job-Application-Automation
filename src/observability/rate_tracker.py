"""Per-resume-UUID response-rate stats.

Tracks: % of submitted applications using each resume variant that received
an interview_invite/recruiter_outreach/offer within 30 days.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select

from src.db.models import Application, ResponseLog
from src.db.session import get_session
from src.util.time import utcnow


def response_rate_by_variant(window_days: int = 30) -> list[dict]:
    """Return per-variant stats sorted by response rate desc."""
    cutoff = utcnow() - timedelta(days=window_days)

    with get_session() as s:
        apps = list(s.scalars(
            select(Application).where(
                Application.applied_at.is_not(None),
                Application.applied_at >= cutoff,
            ),
        ))
        responses = list(s.scalars(select(ResponseLog)))

    high_priority_app_ids = {
        r.application_id for r in responses
        if r.category in ("interview_invite", "recruiter_outreach", "offer")
        and r.application_id is not None
    }

    # Variant comes from notes or resume_pdf path; here we infer from resume_pdf
    # which is named <uuid>__<variant>__... per renderer.py.
    by_variant: defaultdict[str, dict] = defaultdict(lambda: {"submitted": 0, "positive": 0})
    for a in apps:
        variant = _variant_from_pdf(a.resume_pdf) or "(unknown)"
        by_variant[variant]["submitted"] += 1
        if a.id in high_priority_app_ids:
            by_variant[variant]["positive"] += 1

    out = []
    for variant, c in by_variant.items():
        rate = (c["positive"] / c["submitted"]) if c["submitted"] else 0.0
        out.append({
            "variant": variant,
            "submitted": c["submitted"],
            "positive": c["positive"],
            "rate": rate,
        })
    return sorted(out, key=lambda r: r["rate"], reverse=True)


def _variant_from_pdf(pdf_path: str | None) -> str | None:
    if not pdf_path:
        return None
    # renderer.py: <uuid>__<variant>__<company>__<role>.pdf
    name = pdf_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    parts = name.split("__")
    if len(parts) >= 2:
        return parts[1]
    return None
