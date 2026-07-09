"""Telegram bot.

Commands per docs/SPEC.md §7.5:
  /ping, /apply <url>, /pending, /status, /handoff <id>, /done <id>,
  /resume <id>, /profile, /passwords, /edit-password <portal>.

Approval flow uses InlineKeyboardMarkup → callback_query.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from telegram import Update
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
from src.db.session import get_session
from src.llm.rate_limiter import RPD_LIMIT, get_rate_limiter
from src.telegram_bot.allowlist import is_allowed
from src.telegram_bot.cards import Card, pause_card, status_card
from src.util.time import utcnow

log = logging.getLogger(__name__)


class TelegramBot:
    """The live bot. TelegramBotStub is a no-network variant kept for tests."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._app: Application | None = None
        self._pending_approvals: dict[int, asyncio.Future[bool]] = {}
        # app_id → future awaiting a free-text answer to a paused field.
        self._pending_answers: dict[int, asyncio.Future[str]] = {}
        self._bg_tasks: set[asyncio.Task] = set()

    def configured(self) -> bool:
        return bool(
            self.settings.telegram_configured() and not self.settings.no_telegram
        )

    def _require_chat_match(self, chat_id: int) -> bool:
        return is_allowed(chat_id, self.settings.telegram_chat_id)

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        if not self.configured():
            log.warning("telegram bot not started (missing creds or --no-telegram)")
            return
        self._app = Application.builder().token(self.settings.telegram_bot_token).build()
        self._app.add_handler(CommandHandler("ping", self._cmd_ping))
        self._app.add_handler(CommandHandler("apply", self._cmd_apply))
        self._app.add_handler(CommandHandler("pending", self._cmd_pending))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("done", self._cmd_done))
        self._app.add_handler(CommandHandler("profile", self._cmd_profile))
        self._app.add_handler(CommandHandler("passwords", self._cmd_passwords))
        self._app.add_handler(CallbackQueryHandler(self._on_callback))
        # Plain-text replies answer a paused field (HITL learning capture).
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message),
        )
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        log.info("telegram bot polling")

    async def stop(self) -> None:
        if self._app is None:
            return
        try:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        except Exception as e:
            log.warning("telegram shutdown: %s", e)

    async def ping(self) -> bool:
        if not self.configured():
            return False
        from telegram import Bot
        bot = Bot(token=self.settings.telegram_bot_token)
        try:
            await bot.send_message(
                chat_id=self.settings.telegram_chat_id,
                text="pong — apply-agent alive.",
            )
            return True
        except Exception as e:
            log.error("ping failed: %s", e)
            return False

    # --- send helpers ------------------------------------------------------

    async def send_approval(self, card: Card) -> None:
        if self._app is None:
            log.info("[no-telegram] approval card:\n%s", card.text)
            return
        await self._app.bot.send_message(
            chat_id=self.settings.telegram_chat_id,
            text=card.text,
            reply_markup=card.reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    async def send_card(self, card: Card) -> None:
        if self._app is None:
            log.info("[no-telegram] card:\n%s", card.text)
            return
        await self._app.bot.send_message(
            chat_id=self.settings.telegram_chat_id,
            text=card.text,
            reply_markup=card.reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    async def wait_for_approval(self, app_id: int, *, timeout_seconds: int = 600) -> bool:
        """Wait for the user to hit Submit / Reject on the approval card."""
        # Inside async — use get_running_loop(). get_event_loop() is deprecated
        # outside a running loop in 3.12+ and can fail at runtime.
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bool] = loop.create_future()
        self._pending_approvals[app_id] = fut
        try:
            return await asyncio.wait_for(fut, timeout=timeout_seconds)
        except TimeoutError:
            log.warning("approval timeout for app #%s", app_id)
            return False
        finally:
            self._pending_approvals.pop(app_id, None)

    async def ask_question(
        self, app_id: int, question: str, *, timeout_seconds: int = 600,
    ) -> str | None:
        """Post a pause card and wait for the user's free-text reply.

        Returns the reply text, or None on timeout / no bot. The orchestrator
        persists the answer to qa_log so the same field is auto-filled next time.
        """
        if self._app is None:
            log.info("[no-telegram] would ask: %s", question)
            return None
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending_answers[app_id] = fut
        try:
            await self.send_card(pause_card(app_id, question))
            return await asyncio.wait_for(fut, timeout=timeout_seconds)
        except TimeoutError:
            log.warning("answer timeout for app #%s (question=%r)", app_id, question[:60])
            return None
        finally:
            self._pending_answers.pop(app_id, None)

    # --- command handlers --------------------------------------------------

    async def _cmd_ping(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        await update.message.reply_text("pong")

    async def _cmd_apply(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        if not ctx.args:
            await update.message.reply_text("Usage: /apply <url>")
            return
        url = ctx.args[0]
        await update.message.reply_text(f"Queuing application for: {url}")

        # Run the pipeline in the background so the bot stays responsive.
        from src.orchestrator.pipeline import apply_to
        t = asyncio.create_task(_run_apply(apply_to, url, self.settings, self))
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)

    async def _cmd_pending(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        with get_session() as s:
            rows = list(s.scalars(
                select(ApplicationRow)
                .where(ApplicationRow.status.in_(("queued", "tailored")))
                .order_by(ApplicationRow.id.desc())
                .limit(10),
            ))
        if not rows:
            await update.message.reply_text("No pending applications.")
            return
        lines = [f"#{r.id} {r.company} — {r.role_title} ({r.status})" for r in rows]
        await update.message.reply_text("\n".join(lines))

    async def _cmd_status(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        today = utcnow().date()
        week_ago = today - timedelta(days=7)
        today_start = datetime.combine(today, datetime.min.time())
        week_start = datetime.combine(week_ago, datetime.min.time())
        with get_session() as s:
            today_count = s.query(ApplicationRow).filter(
                ApplicationRow.applied_at.isnot(None),
                ApplicationRow.applied_at >= today_start,
            ).count()
            week_count = s.query(ApplicationRow).filter(
                ApplicationRow.applied_at.isnot(None),
                ApplicationRow.applied_at >= week_start,
            ).count()
        rpd_used = get_rate_limiter().day_calls
        card = status_card(today=today_count, week=week_count, rpd_used=rpd_used, rpd_cap=RPD_LIMIT)
        await self.send_card(card)

    async def _cmd_done(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        if not ctx.args:
            await update.message.reply_text("Usage: /done <app_id>")
            return
        try:
            app_id = int(ctx.args[0])
        except ValueError:
            await update.message.reply_text("app_id must be an integer")
            return
        with get_session() as s:
            row = s.get(ApplicationRow, app_id)
            if row is None:
                await update.message.reply_text(f"app #{app_id} not found")
                return
            row.status = "submitted"
            row.applied_at = utcnow()
            row.notes = (row.notes or "") + " | /done by user"
            s.commit()
        await update.message.reply_text(f"✓ app #{app_id} marked submitted")

    async def _cmd_profile(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        try:
            from src.profile.loader import load
            p = load()
            text = (
                f"{p.identity.legal_name}\n"
                f"{p.identity.email}\n"
                f"{p.identity.location.city}, {p.identity.location.state}\n"
                f"Visa: {p.work_authorization.current_status}\n"
                f"Desired: ${p.compensation.desired_base_target:,}"
            )
            await update.message.reply_text(text)
        except Exception as e:
            await update.message.reply_text(f"profile not loaded: {e}")

    async def _cmd_passwords(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        await update.message.reply_text(
            f"Passwords CSV: {self.settings.passwords_csv_path}",
        )

    # --- callback (inline buttons) -----------------------------------------

    async def _on_callback(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._gate(update):
            return
        q = update.callback_query
        await q.answer()
        action, _, sid = (q.data or "").partition(":")
        try:
            app_id = int(sid)
        except ValueError:
            return

        fut = self._pending_approvals.get(app_id)
        if action == "approve" and fut and not fut.done():
            fut.set_result(True)
            await q.edit_message_text(f"✓ Submitted approval for #{app_id}")
        elif action == "reject" and fut and not fut.done():
            fut.set_result(False)
            await q.edit_message_text(f"✗ Rejected #{app_id}")
        elif action == "handoff":
            await q.edit_message_text(f"Handoff requested for #{app_id} — drive in Chrome.")
        elif action == "abort":
            await q.edit_message_text(f"Aborted #{app_id}.")

    async def _on_message(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Route a plain-text reply to the oldest field awaiting an answer."""
        if not self._gate(update) or update.message is None:
            return
        text = (update.message.text or "").strip()
        if not text:
            return
        # Answer the oldest pending question (usual case: exactly one).
        for app_id, fut in list(self._pending_answers.items()):
            if not fut.done():
                fut.set_result(text)
                await update.message.reply_text(f"✓ recorded for #{app_id}; I'll remember it.")
                return
        log.debug("plain message with no pending question; ignoring")

    # --- guards ------------------------------------------------------------

    def _gate(self, update: Update) -> bool:
        chat = update.effective_chat
        if chat is None or not self._require_chat_match(chat.id):
            log.warning("ignored update from chat_id=%s", chat.id if chat else None)
            return False
        return True


async def _run_apply(apply_to, url, settings, bot) -> None:
    try:
        result = await apply_to(url, settings=settings, telegram=bot)
        msg = f"app run: ok={result.ok} reason={result.reason}"
    except Exception as e:
        msg = f"apply_to FAILED: {e}"
        log.exception("apply_to error")
    log.info(msg)
    try:
        if bot._app is not None:
            await bot._app.bot.send_message(
                chat_id=settings.telegram_chat_id, text=msg[:3500],
            )
    except Exception:
        pass


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
        bot = Bot(token=self.settings.telegram_bot_token)
        try:
            await bot.send_message(
                chat_id=self.settings.telegram_chat_id,
                text="pong — apply-agent alive.",
            )
        except Exception as e:
            log.error("telegram ping failed: %s", e)
            return False
        return True
