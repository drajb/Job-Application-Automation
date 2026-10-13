"""IMAP IDLE listener. Pushes new messages to a callback.

Works with any IMAP-over-SSL server. Host/port via env:
  APPLY_EMAIL_IMAP_HOST   (default: imap.gmx.com)
  APPLY_EMAIL_IMAP_PORT   (default: 993)

App passwords are strongly recommended over main account passwords.

Reliability rules:
  - A message is flagged \\Seen only AFTER the handler succeeded. A handler
    failure (Gemini 429, DB lock, Telegram down) leaves it unseen so it is
    retried on the next pass — up to MAX_ATTEMPTS, then it's flagged and
    logged so one poison message can't burn the daily Gemini quota.
  - Socket timeout so a half-open connection can't hang the listener forever.
  - Backoff resets after every successful login.
  - Cancelling `listen()` (shutdown / Ctrl-C) stops the worker thread.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from imap_tools import MailBox, MailMessage

from src.config import Settings

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
HANDLER_TIMEOUT_S = 180


@dataclass
class IncomingEmail:
    uid: str
    from_addr: str
    from_domain: str
    subject: str
    body_text: str
    body_html: str
    received_at: str
    auth_results: str = ""  # Authentication-Results header(s), for DKIM checks
    message_id: str = ""
    in_reply_to: str = ""

    @classmethod
    def from_mail(cls, m: MailMessage) -> IncomingEmail:
        domain = (m.from_ or "").rpartition("@")[2].lower().strip(">").strip()
        headers = {k.lower(): v for k, v in (m.headers or {}).items()}

        def h(name: str) -> str:
            return " ".join(headers.get(name, ()))

        return cls(
            uid=str(m.uid),
            from_addr=m.from_ or "",
            from_domain=domain,
            subject=m.subject or "",
            body_text=m.text or "",
            body_html=m.html or "",
            received_at=(m.date.isoformat() if m.date else ""),
            auth_results=h("authentication-results"),
            message_id=h("message-id"),
            in_reply_to=h("in-reply-to"),
        )


async def listen(
    settings: Settings,
    on_message: Callable[[IncomingEmail], Awaitable[None]],
    *,
    poll_seconds: int = 25,
) -> None:
    """Run until cancelled. Reconnect on errors with backoff.

    Threading: the IDLE call blocks, so `_idle_loop` runs on a worker thread.
    The worker dispatches coroutines back via run_coroutine_threadsafe on the
    main loop captured here.
    """
    if not settings.inbox_configured():
        log.warning("imap listener: APPLY_EMAIL_USER / APPLY_EMAIL_PASSWORD missing, skipping")
        return

    main_loop = asyncio.get_running_loop()
    stop = threading.Event()
    state = {"connected": False}
    attempts: dict[str, int] = {}

    backoff = 5
    try:
        while not stop.is_set():
            state["connected"] = False
            try:
                await asyncio.to_thread(
                    _idle_loop, settings, on_message, poll_seconds, main_loop, stop, state, attempts,
                )
            except Exception as e:
                if state["connected"]:
                    backoff = 5  # we had a working session; start the backoff over
                log.error("imap listener error: %s; reconnecting in %ds", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)
    finally:
        stop.set()


def _idle_loop(
    settings: Settings,
    on_message: Callable[[IncomingEmail], Awaitable[None]],
    poll_seconds: int,
    main_loop: asyncio.AbstractEventLoop,
    stop: threading.Event,
    state: dict,
    attempts: dict[str, int],
) -> None:
    """Blocking IMAP IDLE loop. Runs on a worker thread."""
    with MailBox(
        settings.inbox_imap_host, port=settings.inbox_imap_port, timeout=90,
    ).login(settings.inbox_user or "", settings.inbox_password or "", "INBOX") as mb:
        state["connected"] = True
        log.info("imap connected: %s @ %s", settings.inbox_user, settings.inbox_imap_host)
        while not stop.is_set():
            for m in list(mb.fetch("UNSEEN", mark_seen=False, bulk=True)):
                if stop.is_set() or main_loop.is_closed():
                    return
                ie = IncomingEmail.from_mail(m)
                fut: concurrent.futures.Future[None] = asyncio.run_coroutine_threadsafe(
                    on_message(ie), main_loop,  # type: ignore[arg-type]
                )
                try:
                    fut.result(timeout=HANDLER_TIMEOUT_S)
                    ok = True
                except concurrent.futures.TimeoutError:
                    fut.cancel()
                    log.error("on_message timed out for uid=%s", ie.uid)
                    ok = False
                except Exception as e:
                    log.exception("on_message failed for uid=%s: %s", ie.uid, e)
                    ok = False
                if not ok:
                    attempts[ie.uid] = attempts.get(ie.uid, 0) + 1
                    if attempts[ie.uid] < MAX_ATTEMPTS:
                        continue  # stays UNSEEN → retried next pass
                    log.error("giving up on uid=%s after %d attempts (subject=%r)",
                              ie.uid, MAX_ATTEMPTS, ie.subject[:80])
                attempts.pop(ie.uid, None)
                mb.flag(m.uid or "", "\\Seen", True)
            with contextlib.suppress(Exception):
                mb.idle.wait(timeout=poll_seconds)
