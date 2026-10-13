"""`apply-agent --doctor`: check every prerequisite and say how to fix what's missing.

Read-only and offline except for two optional, harmless network probes
(Telegram getMe, IMAP login) that only run when those credentials are set.
Exit code 0 when nothing required is missing.
"""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import sqlite3
from dataclasses import dataclass

from src.config import (
    DB_PATH,
    MASTER_KEY_PATH,
    PROFILE_ENC_PATH,
    RESUME_SOURCE_DIR,
    Settings,
)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _resumes() -> Check:
    if not RESUME_SOURCE_DIR.exists():
        return Check("resumes", False, f"{RESUME_SOURCE_DIR} does not exist — create "
                     f"resumes/<variant>/<name>.md (see resumes/master/Resume_example.md)")
    mds = [p for p in RESUME_SOURCE_DIR.rglob("*.md") if p.name != "Resume_example.md"]
    if not mds:
        return Check("resumes", False, f"no .md resumes under {RESUME_SOURCE_DIR} besides the "
                     f"example — add your own (one folder per variant)")
    variants = sorted({p.parent.name for p in mds})
    return Check("resumes", True, f"{len(mds)} file(s) in {len(variants)} variant(s): "
                 f"{', '.join(variants[:6])}")


def _db() -> Check:
    if not DB_PATH.exists():
        return Check("database", False, f"{DB_PATH} missing — run `make migrate`")
    try:
        con = sqlite3.connect(DB_PATH)
        ver = con.execute("select version_num from alembic_version").fetchone()
        con.close()
    except sqlite3.Error as e:
        return Check("database", False, f"{e} — run `make migrate`")
    head = _alembic_head()
    if ver and head and ver[0] != head:
        return Check("database", False, f"schema at {ver[0]}, code expects {head} — run `make migrate`")
    return Check("database", True, f"{DB_PATH.name} at revision {ver[0] if ver else '?'}")


def _alembic_head() -> str | None:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        from src.config import REPO_ROOT
        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO_ROOT / "src/db/migrations"))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:
        return None


def _profile() -> Check:
    if not MASTER_KEY_PATH.exists():
        return Check("profile", False, "no master key — run `make keygen` (and back it up)")
    if not PROFILE_ENC_PATH.exists():
        return Check("profile", False, "no encrypted profile — fill secrets/profile.yaml from "
                     "profile.example.yaml, then `make encrypt-profile`")
    try:
        from src.profile.loader import load
        p = load()
    except Exception as e:
        return Check("profile", False, f"can't load: {e}")
    return Check("profile", True, f"loaded ({p.identity.location.city}, "
                 f"{len(p.education)} education entr{'y' if len(p.education) == 1 else 'ies'})")


def _binary(name: str, alts: tuple[str, ...], fix: str, required: bool) -> Check:
    found = next((shutil.which(b) for b in alts if shutil.which(b)), None)
    return Check(name, bool(found), found or f"not found — {fix}", required)


def _module(mod: str, fix: str, required: bool = True) -> Check:
    ok = importlib.util.find_spec(mod) is not None
    return Check(f"python: {mod}", ok, "installed" if ok else fix, required)


def _playwright_browser() -> Check:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            path = p.chromium.executable_path
        import os
        ok = bool(path) and os.path.exists(path)
    except Exception as e:
        return Check("chromium", False, f"{e} — run `python -m playwright install chromium`")
    return Check("chromium", ok, path if ok else "run `python -m playwright install chromium`")


async def _telegram(settings: Settings) -> Check:
    if not settings.telegram_configured():
        return Check("telegram", False, "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — needed "
                     "for approvals (dry runs work without it)", required=False)
    try:
        from telegram import Bot
        me = await Bot(settings.telegram_bot_token or "").get_me()
        return Check("telegram", True, f"bot @{me.username}; allowlisted chat {settings.telegram_chat_id}",
                     required=False)
    except Exception as e:
        return Check("telegram", False, f"token rejected / unreachable: {e}", required=False)


def _inbox(settings: Settings) -> Check:
    if not settings.inbox_configured():
        return Check("inbox", False, "APPLY_EMAIL_USER / APPLY_EMAIL_PASSWORD not set — response "
                     "monitoring + account signup disabled", required=False)
    try:
        from imap_tools import MailBox
        with MailBox(settings.inbox_imap_host, port=settings.inbox_imap_port, timeout=20).login(
            settings.inbox_user or "", settings.inbox_password or "", "INBOX",
        ):
            pass
        return Check("inbox", True, f"logged in to {settings.inbox_imap_host}", required=False)
    except Exception as e:
        return Check("inbox", False, f"IMAP login failed: {e}", required=False)


def _watchlist() -> Check:
    from src.discovery.watchlist import default_path, load
    path = default_path()
    if not path.exists():
        return Check("watchlist", False, "no watchlist.yaml — copy watchlist.example.yaml to "
                     "enable job discovery (/scan)", required=False)
    try:
        wl = load(path)
    except Exception as e:
        return Check("watchlist", False, f"invalid: {e}", required=False)
    return Check("watchlist", True, f"{len(wl.boards)} compan{'y' if len(wl.boards) == 1 else 'ies'}",
                 required=False)


def run(settings: Settings, *, network: bool = True) -> int:
    checks = [
        _resumes(),
        _db(),
        _profile(),
        Check("gemini key", settings.gemini_configured(),
              "set" if settings.gemini_configured() else
              "GEMINI_API_KEY not set — free key at https://aistudio.google.com/apikey"),
        _binary("libreoffice", ("libreoffice", "soffice"),
                "sudo apt install libreoffice --no-install-recommends (needed to make PDFs)",
                required=False),
        _binary("age", ("age-keygen",), "sudo apt install age (for `make keygen`)", required=False),
        _module("sentence_transformers", "pip install -e . (embeddings)", required=False),
        _playwright_browser(),
        _watchlist(),
    ]
    if network:
        checks.append(asyncio.run(_telegram(settings)))
        checks.append(_inbox(settings))

    width = max(len(c.name) for c in checks)
    print("\napply-agent doctor\n")
    for c in checks:
        mark = "✅" if c.ok else ("❌" if c.required else "⚠️ ")
        print(f"  {mark} {c.name.ljust(width)}  {c.detail}")
    missing = [c for c in checks if c.required and not c.ok]
    print()
    if missing:
        print(f"{len(missing)} required item(s) missing. Fix those, then run `make doctor` again.")
        return 1
    print("Ready. Try a dry run:  python -m src.main --apply <job-url>")
    return 0
