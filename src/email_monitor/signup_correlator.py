"""Match incoming verify-email / password-reset / 2fa messages to open expectations.

A signup creates an EmailExpectation row with:
  expected_sender_domain  (e.g. "greenhouse.io")
  expected_subject_regex  (e.g. r"verify.*email")
  purpose                 ("verify_email" | "password_reset" | "2fa")
  expires_at              (typically now+10min)

When IMAP gets a new message, this module checks each open expectation. First
match wins. We extract a link/token and store it in fulfilled_data.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from sqlalchemy import select

from src.db.models import EmailExpectation
from src.db.session import get_session
from src.email_monitor.imap_idle import IncomingEmail
from src.util.time import utcnow

log = logging.getLogger(__name__)

_LINK_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_OTP_RE = re.compile(r"\b(\d{4,8})\b")


def create_expectation(
    *,
    application_id: int | None,
    expected_sender_domain: str,
    purpose: str,
    expected_subject_regex: str | None = None,
    ttl_seconds: int = 600,
) -> int:
    with get_session() as s:
        row = EmailExpectation(
            application_id=application_id,
            expected_sender_domain=expected_sender_domain,
            expected_subject_regex=expected_subject_regex,
            purpose=purpose,
            expires_at=utcnow() + timedelta(seconds=ttl_seconds),
            fulfilled=False,
        )
        s.add(row)
        s.commit()
        return row.id


def match_and_fulfill(msg: IncomingEmail) -> int | None:
    """Return the expectation_id we fulfilled, else None."""
    with get_session() as s:
        now = utcnow()
        rows = list(s.scalars(
            select(EmailExpectation)
            .where(EmailExpectation.fulfilled == False)  # noqa: E712
            .where(
                (EmailExpectation.expires_at.is_(None))
                | (EmailExpectation.expires_at > now),
            ),
        ))
        for row in rows:
            if row.expected_sender_domain.lower() not in msg.from_domain.lower():
                continue
            if row.expected_subject_regex:
                try:
                    if not re.search(row.expected_subject_regex, msg.subject, re.IGNORECASE):
                        continue
                except re.error:
                    continue
            data = _extract(msg, row.purpose)
            row.fulfilled = True
            row.fulfilled_data = data
            s.commit()
            log.info("expectation #%s fulfilled (purpose=%s)", row.id, row.purpose)
            return row.id
    return None


def _extract(msg: IncomingEmail, purpose: str) -> str:
    body = msg.body_text or msg.body_html
    if purpose == "2fa":
        m = _OTP_RE.search(body)
        return m.group(1) if m else ""
    # verify_email / password_reset → first plausible link
    for link in _LINK_RE.findall(body):
        if any(p in link.lower() for p in ("verify", "confirm", "activate", "reset")):
            return link
    # Fallback: first link
    m = _LINK_RE.search(body)
    return m.group(0) if m else ""


async def wait_for_fulfillment(expectation_id: int, *, timeout_seconds: int = 600) -> str | None:
    """Poll the DB until the expectation is fulfilled or timeout."""
    import asyncio

    deadline = utcnow() + timedelta(seconds=timeout_seconds)
    while utcnow() < deadline:
        with get_session() as s:
            row = s.get(EmailExpectation, expectation_id)
            if row is not None and row.fulfilled:
                return row.fulfilled_data or ""
        await asyncio.sleep(3.0)
    return None
