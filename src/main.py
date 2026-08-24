"""Entrypoint. Boots Telegram bot (real or stub), IMAP listener, scheduler.

Flags:
  --no-telegram     skip Telegram entirely
  --dry-run         do not click final-submit anywhere (default ON)
  --no-dry-run      enable real submissions (off by default for safety)
  --ping            send a /ping to Telegram and exit
  --apply <url>     run apply_to(<url>) once and exit
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from dotenv import load_dotenv

from src.config import Settings
from src.telegram_bot.bot import TelegramBot, TelegramBotStub

log = logging.getLogger("apply-agent")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="apply-agent")
    p.add_argument("--no-telegram", action="store_true")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    g.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    p.add_argument("--ping", action="store_true")
    p.add_argument("--apply", metavar="URL", default=None)
    return p.parse_args()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def _ping(settings: Settings) -> int:
    stub = TelegramBotStub(settings)
    ok = await stub.ping()
    return 0 if ok else 1


async def _one_shot_apply(settings: Settings, url: str) -> int:
    from src.orchestrator.pipeline import apply_to
    bot = TelegramBot(settings) if not settings.no_telegram else None
    if bot is not None:
        await bot.start()
    try:
        result = await apply_to(url, settings=settings, telegram=bot)
        log.info("one-shot: ok=%s reason=%s", result.ok, result.reason)
        return 0 if result.ok else 2
    finally:
        if bot is not None:
            await bot.stop()


async def _run_polling(settings: Settings) -> int:
    bot = TelegramBot(settings)
    if not bot.configured():
        log.warning("Telegram not configured; nothing to poll. Exiting.")
        return 0
    await bot.start()

    # Optional services. Each one runs only if its creds are present.
    bg_tasks: list[asyncio.Task] = []
    sched = None

    # IMAP listener (only if an inbox is configured)
    if settings.inbox_configured():
        from src.email_monitor.handler import make_handler
        from src.email_monitor.imap_idle import listen
        handler = await make_handler(settings, telegram=bot)
        bg_tasks.append(asyncio.create_task(listen(settings, handler), name="imap_idle"))
        log.info("IMAP listener started")

    # Scheduler (daily digest at 7pm local)
    try:
        from src.observability.scheduler import start_scheduler
        sched = start_scheduler(telegram=bot)
    except Exception as e:
        log.warning("scheduler not started: %s", e)

    try:
        while True:
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        pass
    finally:
        for t in bg_tasks:
            t.cancel()
        if sched is not None:
            sched.shutdown(wait=False)
        await bot.stop()
    return 0


def main() -> int:
    load_dotenv()
    configure_logging()
    args = parse_args()

    settings = Settings.from_env()
    settings.dry_run = bool(args.dry_run)
    settings.no_telegram = bool(args.no_telegram)
    settings.ping_only = bool(args.ping)

    if not settings.dry_run:
        log.warning("DRY-RUN OFF — real submissions enabled. Make sure you meant this.")
    if not settings.gemini_configured():
        log.warning("GEMINI_API_KEY missing — LLM-dependent modules will be disabled.")
    if not settings.inbox_configured():
        log.warning(
            "APPLY_EMAIL_USER / APPLY_EMAIL_PASSWORD missing — email monitor disabled.",
        )

    try:
        if args.ping:
            return asyncio.run(_ping(settings))
        if args.apply:
            return asyncio.run(_one_shot_apply(settings, args.apply))
        return asyncio.run(_run_polling(settings))
    except KeyboardInterrupt:
        log.info("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
