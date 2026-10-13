"""Match an incoming email to an Application row.

Priority per docs/SPEC.md §7.3:
  1. Sender domain ↔ application.company — the registrable domain's first
     label must EQUAL the normalised company name (no substring / prefix
     guessing: "intuit" must not match "Intuitive Surgical").
  2. Company name as a whole word/phrase in the subject or body. Single
     common-word company names ("Box", "Scale", "Ramp") only count in the
     subject, where false hits are rare.
  3. Orphan (recruiter outreach etc.) → None; still logged by the handler.

Only applications that were actually submitted are candidates, newest first,
so a reply lands on the latest application to that company.
Sender domains of ATS vendors and free-mail providers say nothing about the
company and are skipped for rule 1.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from sqlalchemy import select

from src.db.models import Application
from src.db.session import get_session
from src.email_monitor.imap_idle import IncomingEmail
from src.email_monitor.signup_correlator import registrable_domain
from src.orchestrator.preflight import SUBMITTED_STATUSES
from src.util.time import utcnow

log = logging.getLogger(__name__)

_NEUTRAL_SENDERS = {
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com",
    "myworkday.com", "myworkdayjobs.com", "icims.com", "taleo.net", "jobvite.com",
    "bamboohr.com", "successfactors.com", "oraclecloud.com", "linkedin.com", "indeed.com",
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com",
    "gmx.com", "gmx.net", "proton.me", "protonmail.com", "aol.com", "calendly.com",
}

_SUFFIXES = re.compile(r"\b(inc|llc|ltd|corp|corporation|co|plc|gmbh|technologies|labs|hq)\b\.?")


def _norm_company(name: str) -> str:
    n = _SUFFIXES.sub("", name.lower())
    return re.sub(r"[^a-z0-9]", "", n)


def match(msg: IncomingEmail, *, max_days_old: int = 90) -> Application | None:
    cutoff = utcnow() - timedelta(days=max_days_old)
    with get_session() as s:
        candidates = list(s.scalars(
            select(Application)
            .where(
                Application.status.in_(SUBMITTED_STATUSES),
                Application.applied_at.is_not(None),
                Application.applied_at >= cutoff,
            )
            .order_by(Application.applied_at.desc()),
        ))
    if not candidates:
        return None

    # 1) Sender domain ↔ company name (exact on the domain's first label).
    root = registrable_domain(msg.from_domain)
    if root and root not in _NEUTRAL_SENDERS:
        label = root.split(".")[0]
        for app in candidates:
            if _norm_company(app.company) == label:
                return app

    # 2) Company name as a whole word in subject (always) or body (multi-word
    #    or distinctive names only).
    subject = msg.subject.lower()
    body = (msg.body_text or "").lower()[:5000]
    for app in candidates:
        cname = app.company.strip().lower()
        if not cname or cname.startswith("unknown"):
            continue
        rx = re.compile(rf"(?<![a-z0-9]){re.escape(cname)}(?![a-z0-9])")
        if rx.search(subject):
            return app
        distinctive = " " in cname or len(cname) >= 8
        if distinctive and rx.search(body):
            return app
    return None
