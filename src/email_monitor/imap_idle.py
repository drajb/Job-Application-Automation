"""IMAP IDLE listener. Pushes new messages to a callback.

Works with any IMAP server. Default host/port is overridable via env:
  APPLY_EMAIL_IMAP_HOST   (default: imap.gmx.com)
  APPLY_EMAIL_IMAP_PORT   (default: 993, SSL)

App passwords are strongly recommended over main account passwords.

We use imap_tools' IDLE support: it long-polls the server and yields when
new messages arrive. Reconnect on transient errors with exponential backoff.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from imap_tools import MailBox, MailMessage

from src.config import Settings

log = logging.getLogger(__name__)


@dataclass
class IncomingEmail:
    uid: str
    from_addr: str
    from_domain: str
    subject: str
    body_text: str
    body_html: str
    received_at: str

    @classmethod
    def from_mail(cls, m: MailMessage) -> IncomingEmail:
        domain = (m.from_ or "").rpartition("@")[2].lower()
        return cls(
            uid=str(m.uid),
            from_addr=m.from_ or "",
            from_domain=domain,
            subject=m.subject or "",
            body_text=m.text or "",
            body_html=m.html or "",
            received_at=(m.date.isoformat() if m.date else ""),
        )


async def listen(
    settings: Settings,
    on_message: Callable[[IncomingEmail], Awaitable[None]],
    *,
    poll_seconds: int = 25,
) -> None:
    """Run forever. Reconnect on errors with backoff.

    Threading: the IDLE call blocks, so we run `_idle_loop` on a worker
    thread (`asyncio.to_thread`). The worker dispatches coroutines back
    via `asyncio.run_coroutine_threadsafe(coro, main_loop)`, using the
    main loop reference captured here. Calling `asyncio.get_event_loop()`
    from a worker thread is unsafe in Py 3.10+.
    """
    if not settings.inbox_configured():
        log.warning(
            "imap listener: APPLY_EMAIL_USER / APPLY_EMAIL_PASSWORD missing, skipping",
        )
        return

    main_loop = asyncio.get_running_loop()

    backoff = 5
    while True:
        try:
            await asyncio.to_thread(
                _idle_loop, settings, on_message, poll_seconds, main_loop,
            )
            backoff = 5
        except Exception as e:
            log.error("imap listener crashed: %s; reconnecting in %ds", e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 600)


def _idle_loop(
    settings: Settings,
    on_message: Callable[[IncomingEmail], Awaitable[None]],
    poll_seconds: int,
    main_loop: asyncio.AbstractEventLoop,
) -> None:
    """Blocking IMAP IDLE loop. Runs on a worker thread."""
    with MailBox(settings.inbox_imap_host).login(
        settings.inbox_user, settings.inbox_password, "INBOX",
    ) as mb:
        log.info("imap connected: %s @ %s", settings.inbox_user, settings.inbox_imap_host)
        while True:
            new = list(mb.fetch("UNSEEN", mark_seen=False, bulk=True))
            for m in new:
                ie = IncomingEmail.from_mail(m)
                try:
                    fut = asyncio.run_coroutine_threadsafe(on_message(ie), main_loop)
                    fut.result(timeout=60)
                except Exception as e:
                    log.exception("on_message failed: %s", e)
                # Mark seen after dispatch.
                mb.flag(m.uid, "\\Seen", True)
            # IDLE wait.
            with contextlib.suppress(Exception):
                mb.idle.wait(timeout=poll_seconds)
