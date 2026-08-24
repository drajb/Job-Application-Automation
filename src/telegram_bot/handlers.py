"""Telegram command handlers for /ping. The richer commands (/apply,
/handoff, /done, /resume, /pending, /status, /profile, /passwords, /edit-password."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from src.telegram_bot.allowlist import is_allowed

log = logging.getLogger(__name__)


def make_ping_handler(allowed_chat_id: str | None):
    async def ping(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or update.effective_chat is None:
            return
        if not is_allowed(update.effective_chat.id, allowed_chat_id):
            log.warning(
                "ignored /ping from non-allowlisted chat_id=%s",
                update.effective_chat.id,
            )
            return
        await update.message.reply_text("pong — apply-agent alive.")

    return ping
