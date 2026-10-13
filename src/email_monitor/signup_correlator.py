"""Match incoming verify-email / password-reset / 2fa messages to open expectations.

A signup creates an EmailExpectation row with:
  expected_sender_domain  (registrable domain, e.g. "myworkday.com")
  expected_subject_regex  (e.g. r"verif|confirm")
  purpose                 ("verify_email" | "password_reset" | "2fa")
  expires_at

When IMAP gets a new message, this module checks each open expectation. First
match wins. We extract a link/token and store it in fulfilled_data.

Anti-phishing (docs/SPEC.md §9): a message only fulfils an expectation when
  - its sender domain IS the expected domain or a subdomain of it (never a
    substring — "evilgreenhouse.io" is not "greenhouse.io"),
  - DKIM passed for that domain, when the server recorded an
    Authentication-Results header (a failed/absent-for-domain DKIM rejects),
  - and, for links, the link's host is on the expected domain too.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import select

from src.db.models import EmailExpectation
from src.db.session import get_session
from src.email_monitor.imap_idle import IncomingEmail
from src.util.time import utcnow

log = logging.getLogger(__name__)

_LINK_RE = re.compile(r"https?://[^\s\"'<>()]+", re.IGNORECASE)
_TAG_RE = re.compile(r"<(style|script)[^>]*>.*?</\1>|<[^>]+>", re.IGNORECASE | re.DOTALL)
_OTP_AFTER_KEYWORD = re.compile(
    r"(?:code|otp|passcode|pin|verification|one[- ]time)[^0-9]{0,40}?\b(\d{4,8})\b",
    re.IGNORECASE,
)
_OTP_BEFORE_KEYWORD = re.compile(
    r"\b(\d{4,8})\b[^0-9]{0,30}?(?:is your|verification code|code)",
    re.IGNORECASE,
)

# Public suffixes with two labels that we commonly see. Enough to compute a
# registrable domain without a network-fetched public-suffix list.
_TWO_LEVEL_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz",
    "co.in", "co.jp", "com.br", "com.mx", "co.za", "com.sg", "com.cn", "com.tr",
}


def registrable_domain(host: str) -> str:
    """'careers.acme.co.uk' → 'acme.co.uk'; 'mail.greenhouse.io' → 'greenhouse.io'."""
    parts = [p for p in (host or "").lower().strip(".").split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    if ".".join(parts[-2:]) in _TWO_LEVEL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def domain_matches(actual: str, expected: str) -> bool:
    a, e = actual.lower().strip("."), expected.lower().strip(".")
    return bool(e) and (a == e or a.endswith("." + e))


def dkim_ok(auth_results: str, expected: str) -> bool | None:
    """True = DKIM pass for the expected domain; False = header present but no
    passing signature for it; None = server recorded no Authentication-Results."""
    if not auth_results.strip():
        return None
    for m in re.finditer(r"dkim=(\w+)[^;]*?header\.(?:d|i)=@?([\w.-]+)", auth_results, re.I):
        if m.group(1).lower() == "pass" and domain_matches(m.group(2), expected):
            return True
    return False


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


def refresh_expectation(expectation_id: int, *, ttl_seconds: int) -> None:
    """Restart an expectation's clock (call it when you actually start waiting)."""
    with get_session() as s:
        row = s.get(EmailExpectation, expectation_id)
        if row is not None and not row.fulfilled:
            row.expires_at = utcnow() + timedelta(seconds=ttl_seconds)
            s.commit()


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
            )
            .order_by(EmailExpectation.created_at.desc()),
        ))
        for row in rows:
            expected = row.expected_sender_domain
            if not domain_matches(msg.from_domain, expected):
                continue
            dk = dkim_ok(msg.auth_results, expected)
            if dk is False:
                log.warning("expectation #%s: sender %s matched but DKIM did not pass — ignoring "
                            "(possible spoof)", row.id, msg.from_domain)
                continue
            if dk is None:
                log.info("expectation #%s: no Authentication-Results header; relying on "
                         "sender + link-host checks", row.id)
            if row.expected_subject_regex:
                try:
                    if not re.search(row.expected_subject_regex, msg.subject, re.IGNORECASE):
                        continue
                except re.error:
                    continue
            data = extract(msg, row.purpose, expected)
            if not data:
                log.warning("expectation #%s: matching email had no usable %s", row.id, row.purpose)
                continue
            row.fulfilled = True
            row.fulfilled_data = data
            s.commit()
            log.info("expectation #%s fulfilled (purpose=%s)", row.id, row.purpose)
            return row.id
    return None


def _plain(msg: IncomingEmail) -> str:
    if msg.body_text.strip():
        return html.unescape(msg.body_text)
    return html.unescape(_TAG_RE.sub(" ", msg.body_html or ""))


def _links(msg: IncomingEmail) -> list[str]:
    raw = html.unescape(f"{msg.body_text}\n{msg.body_html}")
    out = []
    for link in _LINK_RE.findall(raw):
        link = link.rstrip(".,;:!?'\"]>")
        if link not in out:
            out.append(link)
    return out


def extract(msg: IncomingEmail, purpose: str, expected_domain: str = "") -> str:
    if purpose == "2fa":
        text = _plain(msg)
        for rx in (_OTP_AFTER_KEYWORD, _OTP_BEFORE_KEYWORD):
            for m in rx.finditer(text):
                code = m.group(1)
                if not re.fullmatch(r"(?:19|20)\d{2}", code):
                    return code
        return ""
    # verify_email / password_reset → a link on the expected domain
    links = [
        u for u in _links(msg)
        if not expected_domain or domain_matches(urlparse(u).hostname or "", expected_domain)
    ]
    for link in links:
        if re.search(r"verif|confirm|activat|reset|token|validate", link, re.I):
            return link
    return links[0] if len(links) == 1 else ""


# Backwards-compatible alias (older code/tests call the private name).
def _extract(msg: IncomingEmail, purpose: str) -> str:
    return extract(msg, purpose)


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
