"""Entrypoint. Boots the Telegram bot, IMAP listener and scheduler — or runs a
one-shot command.

Daemon:
  python -m src.main                 bot + inbox monitor + scheduler (dry-run)
  python -m src.main --no-dry-run    ... with real submissions (needs Telegram)
  python -m src.main --no-telegram   inbox monitor + scheduler only

One-shot:
  --apply URL        run one application and exit
  --scan             scan your watchlist for new matching roles
  --fit URL_OR_FILE  resume fit + keyword-gap report for one posting
  --doctor           check your setup and explain what's missing
  --done ID          record an application you finished manually
  --export PATH      export your applications to CSV
  --ping             send a Telegram ping and exit
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from src.config import Settings
from src.telegram_bot.bot import TelegramBot, TelegramBotStub

log = logging.getLogger("apply-agent")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="apply-agent",
        description="Truthful, human-in-the-loop job applications.",
    )
    p.add_argument("--no-telegram", action="store_true", help="run without the Telegram bot")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", dest="dry_run", action="store_true", default=True,
                   help="fill forms but never click Submit (default)")
    g.add_argument("--no-dry-run", dest="dry_run", action="store_false",
                   help="allow real submissions (each one still needs your Telegram approval)")
    cmd = p.add_mutually_exclusive_group()
    cmd.add_argument("--ping", action="store_true", help="send a Telegram ping and exit")
    cmd.add_argument("--apply", metavar="URL", help="apply to one posting and exit")
    cmd.add_argument("--scan", action="store_true", help="scan the watchlist and exit")
    cmd.add_argument("--fit", metavar="URL_OR_FILE", help="fit + keyword-gap report and exit")
    cmd.add_argument("--doctor", action="store_true", help="check setup and exit")
    cmd.add_argument("--done", metavar="ID", type=int, help="mark an application submitted")
    cmd.add_argument("--export", metavar="PATH", help="export applications to CSV and exit")
    p.add_argument("--all", action="store_true", help="with --scan: include already-seen roles")
    p.add_argument("--offline", action="store_true", help="with --doctor: skip network checks")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p.parse_args(argv)


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "apscheduler", "telegram.ext", "sentence_transformers",
                  "alembic", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


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


async def _run_daemon(settings: Settings) -> int:
    bot = TelegramBot(settings)
    await bot.start()
    live = bot._app is not None
    if not live:
        log.warning("Telegram is off — running inbox monitor + scheduler only. "
                    "Use --apply <url> for one-shot dry runs.")

    bg_tasks: list[asyncio.Task] = []
    sched = None
    if settings.inbox_configured():
        from src.email_monitor.handler import make_handler
        from src.email_monitor.imap_idle import listen
        handler = await make_handler(settings, telegram=bot if live else None)
        bg_tasks.append(asyncio.create_task(listen(settings, handler), name="imap_idle"))
        log.info("IMAP listener started")

    try:
        from src.observability.scheduler import start_scheduler
        sched = start_scheduler(telegram=bot if live else None)
    except Exception as e:
        log.warning("scheduler not started: %s", e)

    if not live and not bg_tasks and sched is None:
        log.warning("nothing to run (no Telegram, no inbox). Exiting.")
        return 0
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        for t in bg_tasks:
            t.cancel()
        if bg_tasks:
            await asyncio.gather(*bg_tasks, return_exceptions=True)
        if sched is not None:
            sched.shutdown(wait=False)
        await bot.stop()
    return 0


def _scan(include_seen: bool) -> int:
    from rich.console import Console
    from rich.table import Table

    from src.discovery.scan import scan, set_status
    from src.discovery.watchlist import load

    try:
        wl = load()
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    found = asyncio.run(scan(wl, include_seen=include_seen))
    if not found:
        print("No new matching roles. (Use --all to show ones you've already seen.)")
        return 0
    t = Table(title=f"Top {len(found)} matching roles")
    for col in ("#", "Fit", "Company", "Role", "Location", "Missing keywords", "URL"):
        t.add_column(col, overflow="fold")
    for sp in found:
        p = sp.posting
        t.add_row(str(sp.job_id or ""), f"{sp.fit.percent}%", p.company, p.title,
                  p.location or ("Remote" if p.remote else ""), ", ".join(sp.fit.missing[:5]), p.url)
        if sp.job_id and not sp.seen_before:
            set_status(sp.job_id, "notified")
    Console().print(t)
    print("\nApply with:  python -m src.main --apply <URL>   (or tap 🚀 in Telegram after /scan)")
    return 0


def _fit(target: str) -> int:
    from pathlib import Path

    from src.discovery.fit import score_fit
    from src.discovery.scan import load_resume_corpus

    if target.startswith(("http://", "https://")):
        import httpx

        from src.company_research.scraper import _html_to_text
        try:
            r = httpx.get(target, follow_redirects=True, timeout=20,
                          headers={"User-Agent": "Mozilla/5.0 apply-agent"})
            r.raise_for_status()
        except httpx.HTTPError as e:
            print(f"error: couldn't fetch {target}: {e}", file=sys.stderr)
            return 1
        jd = _html_to_text(r.text)
    else:
        path = Path(target)
        if not path.exists():
            print(f"error: {target} is neither a URL nor a file", file=sys.stderr)
            return 1
        jd = path.read_text(encoding="utf-8", errors="replace")
    resume = load_resume_corpus()
    if not resume:
        print("error: no resumes found (RESUME_SOURCE_DIR)", file=sys.stderr)
        return 1
    from collections.abc import Callable
    from typing import Any

    embed_fn: Callable[[str], Any] | None = None
    try:
        from src.resume.embeddings import embed
        embed_fn = embed
    except Exception:
        log.info("embeddings unavailable; keyword scoring only")
    rep = score_fit(jd, resume, embed_fn=embed_fn)
    print(f"\nFit: {rep.percent}%")
    if rep.keyword_coverage is not None:
        print(f"  keyword coverage: {round(rep.keyword_coverage * 100)}% "
              f"({len(rep.matched)}/{len(rep.matched) + len(rep.missing)})")
    if rep.semantic is not None:
        print(f"  semantic similarity: {rep.semantic:.2f}")
    print(f"\n✅ In your resume: {', '.join(rep.matched) or '—'}")
    print(f"❌ Asked for, not in your resume: {', '.join(rep.missing) or '—'}")
    print("\nOnly add a missing keyword to your SOURCE resume if it's true — the tailor will "
          "never add it for you (the validator would reject it).")
    return 0


def _export(path: str) -> int:
    import csv

    from sqlalchemy import select

    from src.db.models import Application
    from src.db.session import get_session

    cols = ["id", "company", "role_title", "status", "ats", "tier_used", "applied_at",
            "response_at", "resume_uuid", "url"]
    with get_session() as s, open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        n = 0
        for a in s.scalars(select(Application).order_by(Application.id)):
            w.writerow([getattr(a, c) if getattr(a, c) is not None else "" for c in cols])
            n += 1
    print(f"exported {n} application(s) to {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    settings = Settings.from_env()
    settings.dry_run = bool(args.dry_run)
    settings.no_telegram = bool(args.no_telegram)
    settings.ping_only = bool(args.ping)

    if args.doctor:
        from src.doctor import run as doctor
        return doctor(settings, network=not args.offline)
    if args.scan:
        return _scan(args.all)
    if args.fit:
        return _fit(args.fit)
    if args.export:
        return _export(args.export)
    if args.done is not None:
        from src.telegram_bot.bot import mark_done
        ok = mark_done(args.done)
        print(f"app #{args.done} marked submitted" if ok else f"app #{args.done} not found")
        return 0 if ok else 1

    if not settings.dry_run:
        if settings.no_telegram or not settings.telegram_configured():
            log.error("--no-dry-run needs Telegram: every real submission must be approved by "
                      "you. Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID, or stay in dry-run.")
            return 2
        log.warning("DRY-RUN OFF — real submissions enabled (each still needs your approval).")
    if not settings.gemini_configured():
        log.warning("GEMINI_API_KEY missing — tailoring disabled; email classification falls "
                    "back to keyword rules.")
    if not settings.inbox_configured():
        log.warning("APPLY_EMAIL_USER / APPLY_EMAIL_PASSWORD missing — email monitor disabled.")

    try:
        if args.ping:
            return asyncio.run(_ping(settings))
        if args.apply:
            return asyncio.run(_one_shot_apply(settings, args.apply))
        return asyncio.run(_run_daemon(settings))
    except KeyboardInterrupt:
        log.info("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
