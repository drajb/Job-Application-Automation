"""Match an incoming email to an Application row.

Priority per docs/SPEC.md §7.3:
  1. Message-ID threading (not yet implemented — needs an SMTP-side message ID stamp)
  2. Sender domain ↔ application.company (fuzzy)
  3. Fuzzy company match in subject/body
  4. Orphan recruiter outreach → still logged with application_id=None
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from sqlalchemy import select

from src.db.models import Application
from src.db.session import get_session
from src.email_monitor.imap_idle import IncomingEmail
from src.util.time import utcnow

log = logging.getLogger(__name__)


def match(msg: IncomingEmail, *, max_days_old: int = 90) -> Application | None:
    cutoff = utcnow() - timedelta(days=max_days_old)
    with get_session() as s:
        candidates = list(s.scalars(
            select(Application).where(
                (Application.applied_at.is_(None))
                | (Application.applied_at >= cutoff),
            ),
        ))

    if not candidates:
        return None

    # 2) Sender domain ↔ company name (fuzzy)
    root = _root_domain(msg.from_domain)
    for app in candidates:
        cname = re.sub(r"[^a-z0-9]", "", app.company.lower())
        if cname and (cname in root or root.startswith(cname[:6])):
            return app

    # 3) Fuzzy company match in subject + body excerpt
    haystack = (msg.subject + " " + (msg.body_text or "")).lower()
    for app in candidates:
        cname = app.company.lower()
        if not cname or cname == "unknown":
            continue
        if cname in haystack:
            return app

    return None


def _root_domain(host: str) -> str:
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    return ".".join(parts[-2:])
