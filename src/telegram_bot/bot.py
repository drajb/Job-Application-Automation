"""Telegram bot — the human-in-the-loop control surface.

Commands:
  /start, /help          what the bot can do
  /ping                  liveness
  /apply <url>           tailor + fill + ask for approval (one at a time)
  /scan                  scan your watchlist for new matching roles
  /pending               applications waiting on you
  /status                today / week totals, responses, Gemini quota
  /done <id>             you finished an application manually
  /abort <id>            stop an in-flight application
  /profile               redacted profile summary
  /passwords             where the password CSV mirror lives

Every update — commands, button presses, free-text replies — passes the
chat_id allowlist (`_gate`) first. Cards use HTML parse mode.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.config import Settings
from src.db.models import Application as ApplicationRow
from src.db.models import ResponseLog
from src.db.session import get_session
from src.llm.rate_limiter import get_rate_limiter
from src.telegram_bot.allowlist import is_allowed
from src.telegram_bot.cards import Card, discovered_job_card, pause_card, status_card
from src.util.time import local_day_bounds_utc, utcnow

log = logging.getLogger(__name__)

_COMMANDS = [
    ("apply", "Apply to a job URL"),
    ("scan", "Scan your watchlist for new roles"),
    ("pending", "Applications waiting on you"),
    ("status", "Today / week stats + quota"),
    ("done", "Mark an application finished manually"),
    ("abort", "Stop an in-flight application"),
    ("profile", "Redacted profile summary"),
    ("help", "What I can do"),
]

_HELP = (
    "<b>apply-agent</b> — truthful, human-in-the-loop job applications.\n\n"
    "/apply &lt;url&gt; — tailor your resume, fill the form, and show it to you before anything is sent\n"
    "/scan — find new roles at the companies in your watchlist\n"
    "/pending — what's waiting on you\n"
    "/status — today's numbers and Gemini quota\n"
    "/done &lt;id&gt; — you finished one manually\n"
    "/abort &lt;id&gt; — stop one\n"
    "/profile — redacted profile\n\n"
    "When I ask a question, <i>reply to that message</i> with the answer — I'll remember it."
)


class TelegramBot:
    """The live bot. TelegramBotStub is a no-network variant kept for tests."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._app: Application | None = None
        self._pending_approvals: dict[int, asyncio.Future[str]] = {}
        # message_id of a sent question card → (app_id, future awaiting the reply)
        self._pending_answers: dict[int, tuple[int, asyncio.Future[str | None]]] = {}
        self._pending_done: dict[int, asyncio.Future[str]] = {}
        self._aborted: set[int] = set()
        self._takeover: set[int] = set()
        self._bg_tasks: set[asyncio.Task] = set()

    def configured(self) -> bool:
        return bool(self.settings.telegram_configured() and not self.settings.no_telegram)

    def _require_chat_match(self, chat_id: int) -> bool:
        return is_allowed(chat_id, self.settings.telegram_chat_id)

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        if not self.configured():
            log.warning("telegram bot not started (missing creds or --no-telegram)")
            return
        app = Application.builder().token(self.settings.telegram_bot_token or "").build()
        only_new = filters.UpdateType.MESSAGE  # ignore edited messages
        for name, fn in (
            ("start", self._cmd_help), ("help", self._cmd_help), ("ping", self._cmd_ping),
            ("apply", self._cmd_apply), ("scan", self._cmd_scan), ("pending", self._cmd_pending),
            ("status", self._cmd_status), ("done", self._cmd_done), ("abort", self._cmd_abort),
            ("profile", self._cmd_profile), ("passwords", self._cmd_passwords),
        ):
            app.add_handler(CommandHandler(name, fn, filters=only_new))
        app.add_handler(CallbackQueryHandler(self._on_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & only_new, self._on_message))
        app.add_error_handler(self._on_error)
        await app.initialize()
        await app.start()
        if app.updater is not None:
            await app.updater.start_polling(drop_pending_updates=True)
        self._app = app
        try:
            await app.bot.set_my_commands([BotCommand(c, d) for c, d in _COMMANDS])
        except Exception as e:
            log.debug("set_my_commands failed: %s", e)
        log.info("telegram bot polling")

    async def stop(self) -> None:
        if self._app is None:
            return
        try:
            if self._app.updater is not None:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        except Exception as e:
            log.warning("telegram shutdown: %s", e)
        finally:
            self._app = None

    async def ping(self) -> bool:
        if not self.configured():
            return False
        from telegram import Bot
        bot = Bot(token=self.settings.telegram_bot_token or "")
        try:
            await bot.send_message(chat_id=self.settings.telegram_chat_id or "",
                                   text="pong — apply-agent alive.")
            return True
        except Exception as e:
            log.error("ping failed: %s", e)
            return False

    # --- send helpers ------------------------------------------------------

    async def send_card(self, card: Card):
        if self._app is None:
            log.info("[no-telegram] card:\n%s", card.text)
            return None
        return await self._app.bot.send_message(
            chat_id=self.settings.telegram_chat_id,
            text=card.text,
            reply_markup=card.reply_markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    # Kept for callers of the old name.
    send_approval = send_card

    async def send_html(self, text: str):
        return await self.send_card(Card(text=text))

    async def send_text(self, text: str) -> None:
        if self._app is None:
            log.info("[no-telegram] %s", text)
            return
        await self._app.bot.send_message(chat_id=self.settings.telegram_chat_id, text=text[:4000])

    async def send_photo(self, path: Path, caption: str = "") -> None:
        if self._app is None or not Path(path).exists():
            return
        with Path(path).open("rb") as fh:
            await self._app.bot.send_photo(
                chat_id=self.settings.telegram_chat_id, photo=fh, caption=caption[:1000],
            )

    # --- waits used by the pipeline ------------------------------------------

    async def wait_for_approval(self, app_id: int, *, timeout_seconds: int = 1800) -> str:
        """'approve' | 'reject' | 'handoff' | 'timeout'."""
        if self._app is None:
            return "timeout"
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending_approvals[app_id] = fut
        try:
            return await asyncio.wait_for(fut, timeout=timeout_seconds)
        except TimeoutError:
            log.warning("approval timeout for app #%s", app_id)
            return "timeout"
        finally:
            self._pending_approvals.pop(app_id, None)

    async def ask_question(
        self, app_id: int, question: str, *, timeout_seconds: int = 900,
    ) -> str | None:
        """Post a question card and wait for the reply to THAT message.

        Returns the reply text, or None on timeout / skip / abort / no bot.
        """
        if self._app is None:
            log.info("[no-telegram] would ask: %s", question)
            return None
        fut: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        msg = await self.send_card(pause_card(app_id, question))
        msg_id = getattr(msg, "message_id", None) or -app_id
        self._pending_answers[msg_id] = (app_id, fut)
        try:
            return await asyncio.wait_for(fut, timeout=timeout_seconds)
        except TimeoutError:
            log.warning("answer timeout for app #%s (question=%r)", app_id, question[:60])
            return None
        finally:
            self._pending_answers.pop(msg_id, None)

    async def wait_for_done(self, app_id: int, *, timeout_seconds: float = 1800) -> str:
        """Wait for /done <id> ('done') or /abort <id> ('aborted'); else 'timeout'."""
        if self._app is None:
            return "timeout"
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending_done[app_id] = fut
        try:
            return await asyncio.wait_for(fut, timeout=timeout_seconds)
        except TimeoutError:
            return "timeout"
        finally:
            self._pending_done.pop(app_id, None)

    def abort_requested(self, app_id: int) -> bool:
        return app_id in self._aborted

    def takeover_requested(self, app_id: int) -> bool:
        return app_id in self._takeover

    def _resolve_all(self, app_id: int, *, approval: str, answer: str | None, done: str) -> None:
        if (f := self._pending_approvals.get(app_id)) and not f.done():
            f.set_result(approval)
        for _mid, (aid, f2) in list(self._pending_answers.items()):
            if aid == app_id and not f2.done():
                f2.set_result(answer)
        if (f3 := self._pending_done.get(app_id)) and not f3.done():
            f3.set_result(done)

    # --- command handlers --------------------------------------------------

    async def _cmd_help(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        await _reply(update, _HELP, parse_mode=ParseMode.HTML)

    async def _cmd_ping(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        await _reply(update, "pong")

    async def _cmd_apply(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        if not ctx.args or not ctx.args[0].startswith(("http://", "https://")):
            await _reply(update, "Usage: /apply https://<job posting url>")
            return
        await self._start_apply(ctx.args[0])
        await _reply(update, 
            f"Queued ({'dry run' if self.settings.dry_run else 'LIVE'}): {ctx.args[0]}",
            disable_web_page_preview=True,
        )

    async def _start_apply(self, url: str) -> None:
        # Background task so the bot stays responsive; the pipeline serialises runs.
        from src.orchestrator.pipeline import apply_to
        t = asyncio.create_task(_run_apply(apply_to, url, self.settings, self))
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)

    async def _cmd_scan(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        await _reply(update, "Scanning your watchlist…")
        t = asyncio.create_task(self.run_scan(announce_empty=True))
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)

    async def run_scan(self, *, announce_empty: bool = False) -> int:
        """Scan the watchlist and post one card per new matching role."""
        from src.discovery.scan import scan, set_status
        from src.discovery.watchlist import load

        try:
            wl = load()
        except Exception as e:
            await self.send_text(f"Scan skipped: {e}")
            return 0
        try:
            found = await scan(wl)
        except Exception as e:
            log.exception("scan failed")
            await self.send_text(f"Scan failed: {e}")
            return 0
        if not found and announce_empty:
            await self.send_text("No new matching roles since the last scan.")
        for sp in found:
            p = sp.posting
            await self.send_card(discovered_job_card(
                job_id=sp.job_id or 0, company=p.company, title=p.title, location=p.location,
                url=p.url, fit_percent=sp.fit.percent, missing=sp.fit.missing, remote=p.remote,
            ))
            if sp.job_id:
                set_status(sp.job_id, "notified")
        return len(found)

    async def _cmd_pending(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        with get_session() as s:
            rows = list(s.scalars(
                select(ApplicationRow)
                .where(ApplicationRow.status.in_(("queued", "tailored", "handoff", "deferred",
                                                  "submit_unverified")))
                .order_by(ApplicationRow.id.desc())
                .limit(15),
            ))
        if not rows:
            await _reply(update, "Nothing waiting on you.")
            return
        lines = [f"#{r.id} {r.company} — {r.role_title} ({r.status})" for r in rows]
        await _reply(update, "\n".join(lines))

    async def _cmd_status(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        from src.orchestrator.preflight import SUBMITTED_STATUSES

        today_start, _ = local_day_bounds_utc()
        week_start = utcnow() - timedelta(days=7)
        with get_session() as s:
            def count(*conds):
                return s.scalar(select(func.count(ApplicationRow.id)).where(*conds)) or 0
            today = count(ApplicationRow.status.in_(SUBMITTED_STATUSES),
                          ApplicationRow.applied_at >= today_start)
            week = count(ApplicationRow.status.in_(SUBMITTED_STATUSES),
                         ApplicationRow.applied_at >= week_start)
            pending = count(ApplicationRow.status.in_(("handoff", "submit_unverified", "deferred")))
            resp = list(s.scalars(select(ResponseLog.category).where(
                ResponseLog.classified_at >= week_start)))
        lim = get_rate_limiter()
        await self.send_card(status_card(
            today=today, week=week, rpd_used=lim.day_calls, rpd_cap=lim.rpd_limit,
            pending=pending, responses_week=len(resp),
            interviews_week=sum(1 for c in resp if c in ("interview_invite", "offer")),
        ))

    def _app_id_arg(self, ctx) -> int | None:
        try:
            return int(ctx.args[0]) if ctx.args else None
        except ValueError:
            return None

    async def _cmd_done(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        app_id = self._app_id_arg(ctx)
        if app_id is None:
            await _reply(update, "Usage: /done <app_id>")
            return
        if not mark_done(app_id):
            await _reply(update, f"app #{app_id} not found")
            return
        self._resolve_all(app_id, approval="reject", answer=None, done="done")
        await _reply(update, f"✓ app #{app_id} marked submitted")

    async def _cmd_abort(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        app_id = self._app_id_arg(ctx)
        if app_id is None:
            await _reply(update, "Usage: /abort <app_id>")
            return
        self._aborted.add(app_id)
        self._resolve_all(app_id, approval="reject", answer=None, done="aborted")
        await _reply(update, f"🛑 app #{app_id} aborted")

    async def _cmd_profile(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        try:
            from src.profile.loader import load
            p = load()
        except Exception as e:
            await _reply(update, f"profile not loaded: {type(e).__name__}")
            return
        name = p.identity.legal_name.split()
        email = str(p.identity.email)
        user, _, dom = email.partition("@")
        text = (
            f"Name: {name[0] if name else '?'} {name[-1][0] + '.' if len(name) > 1 else ''}\n"
            f"Email: {user[:2]}…@{dom}\n"
            f"Location: {p.identity.location.city}, {p.identity.location.state}\n"
            f"Work authorization set: {'yes' if p.work_authorization else 'no'}\n"
            f"Salary target set: {'yes' if p.compensation.desired_base_target else 'no'}\n"
            f"Education entries: {len(p.education)}"
        )
        await _reply(update, text)

    async def _cmd_passwords(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        await _reply(update, 
            f"Passwords CSV mirror (on the agent's machine): {self.settings.passwords_csv_path}",
        )

    # --- callback (inline buttons) -----------------------------------------

    async def _on_callback(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        q = update.callback_query
        if q is None:
            return
        await q.answer()
        msg: Any = q.message
        if msg is None:
            return
        action, _, sid = (q.data or "").partition(":")
        try:
            obj_id = int(sid)
        except ValueError:
            return

        if action in ("jobapply", "jobskip"):
            await self._on_job_button(q, action, obj_id)
            return

        app_id = obj_id
        fut = self._pending_approvals.get(app_id)
        if action in ("approve", "reject"):
            if fut is None or fut.done():
                await q.edit_message_reply_markup(reply_markup=None)
                await msg.reply_text(f"app #{app_id}: that approval already expired.")
                return
            fut.set_result(action)
            await q.edit_message_reply_markup(reply_markup=None)
            await msg.reply_text(
                f"✓ approved #{app_id}" if action == "approve" else f"✗ rejected #{app_id}",
            )
        elif action == "handoff":
            self._takeover.add(app_id)
            self._resolve_all(app_id, approval="handoff", answer=None, done="timeout")
            await q.edit_message_reply_markup(reply_markup=None)
            await msg.reply_text(
                f"🖥 #{app_id}: the browser window is yours — finish it, then /done {app_id}.",
            )
        elif action == "abort":
            self._aborted.add(app_id)
            self._resolve_all(app_id, approval="reject", answer=None, done="aborted")
            await q.edit_message_reply_markup(reply_markup=None)
            await msg.reply_text(f"🛑 aborted #{app_id}")
        elif action == "skip":
            for mid, (aid, f) in list(self._pending_answers.items()):
                if aid == app_id and mid == msg.message_id and not f.done():
                    f.set_result(None)
            await q.edit_message_reply_markup(reply_markup=None)

    async def _on_job_button(self, q: Any, action: str, job_id: int) -> None:
        from src.discovery.scan import set_status

        row = set_status(job_id, "applied" if action == "jobapply" else "dismissed")
        msg: Any = q.message
        await q.edit_message_reply_markup(reply_markup=None)
        if row is None:
            await msg.reply_text("That job is no longer in the database.")
            return
        if action == "jobapply":
            await self._start_apply(row.url)
            await msg.reply_text(f"Queued: {row.company} — {row.title}")

    async def _on_message(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Route a free-text reply to the question it answers."""
        if not self._gate(update) or update.effective_message is None:
            return
        msg = update.effective_message
        text = (msg.text or "").strip()
        if not text:
            return
        open_qs = {mid: v for mid, v in self._pending_answers.items() if not v[1].done()}
        target = None
        if msg.reply_to_message is not None:
            target = open_qs.get(msg.reply_to_message.message_id)
        elif len(open_qs) == 1:
            target = next(iter(open_qs.values()))
        if target is None:
            if len(open_qs) > 1:
                await msg.reply_text("Several questions are open — reply directly to the one "
                                     "you're answering.")
            return
        app_id, fut = target
        fut.set_result(text)
        await msg.reply_text(f"✓ recorded for #{app_id}; I'll remember it.")

    async def _on_error(self, update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("telegram handler error: %s", ctx.error, exc_info=ctx.error)

    # --- guards ------------------------------------------------------------

    def _gate(self, update: Update) -> bool:
        chat = update.effective_chat
        if chat is None or not self._require_chat_match(chat.id):
            log.warning("ignored update from chat_id=%s", chat.id if chat else None)
            return False
        return True


async def _reply(update: Update, text: str, **kw: Any) -> None:
    msg = update.effective_message
    if msg is not None:
        await msg.reply_text(text, **kw)


def mark_done(app_id: int) -> bool:
    """Record a manual submission. Shared by /done and the --done CLI flag."""
    with get_session() as s:
        row = s.get(ApplicationRow, app_id)
        if row is None:
            return False
        row.status = "submitted"
        row.applied_at = row.applied_at or utcnow()
        row.notes = (row.notes or "") + " | /done by user"
        s.commit()
    return True


async def _run_apply(apply_to, url, settings, bot) -> None:
    try:
        result = await apply_to(url, settings=settings, telegram=bot)
        icon = "✅" if result.ok else "📝"
        app = f" #{result.application_id}" if result.application_id else ""
        msg = f"{icon} app{app}: {result.reason}"
    except Exception as e:
        msg = f"apply_to FAILED: {e}"
        log.exception("apply_to error")
    log.info(msg)
    try:
        await bot.send_text(msg)
    except Exception:
        log.debug("could not send result message", exc_info=True)


# --- no-network stub used by tests ------------------------------------------


class TelegramBotStub:
    """No-network variant for tests. Same surface as TelegramBot, no polling."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._app: object | None = None

    def _should_skip(self) -> tuple[bool, str]:
        if self.settings.no_telegram:
            return True, "--no-telegram flag set"
        if not self.settings.telegram_configured():
            missing = []
            if not self.settings.telegram_bot_token:
                missing.append("TELEGRAM_BOT_TOKEN")
            if not self.settings.telegram_chat_id:
                missing.append("TELEGRAM_CHAT_ID")
            return True, f"missing env: {', '.join(missing)}"
        return False, ""

    async def start_if_configured(self) -> None:
        skip, why = self._should_skip()
        if skip:
            log.warning("telegram disabled: %s. Continuing without bot.", why)
            return
        log.info("telegram credentials present; long-polling deferred to bot run")

    async def stop_if_configured(self) -> None:
        return

    async def ping(self) -> bool:
        skip, why = self._should_skip()
        if skip:
            log.error("cannot --ping: %s", why)
            return False
        from telegram import Bot
        bot = Bot(token=self.settings.telegram_bot_token or "")
        try:
            await bot.send_message(
                chat_id=self.settings.telegram_chat_id or "",
                text="pong — apply-agent alive.",
            )
        except Exception as e:
            log.error("telegram ping failed: %s", e)
            return False
        return True
