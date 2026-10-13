"""Runtime config: env vars, CLI flags, paths.

Owns the resolution of every tunable knob. Single import point so nothing else
reads os.environ directly. Flags (--dry-run, --no-telegram, --ping) live here
too; parsed once in main.py and stashed on the Settings object.

Locked architectural decisions live in docs/SPEC.md §11. Do not introduce new
env vars that violate them (e.g. do not add OPENAI_API_KEY or
ANTHROPIC_API_KEY — this project uses Gemini only, free tier).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Repo root (apply-agent/), resolved from this file's location.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]

# Load .env BEFORE resolving the module-level paths below — otherwise
# RESUME_SOURCE_DIR / APPLY_AGENT_DB set in .env would be silently ignored
# (other modules import these constants at import time). Real environment
# variables always win over .env. Tests set APPLY_AGENT_NO_DOTENV=1.
if not os.environ.get("APPLY_AGENT_NO_DOTENV"):
    load_dotenv(REPO_ROOT / ".env", override=False)

SECRETS_DIR: Path = REPO_ROOT / "secrets"
DATA_DIR: Path = REPO_ROOT / "data"

# Default resume source directory. Override with RESUME_SOURCE_DIR env var if
# your resumes live outside the repo (recommended — keeps your private CV out
# of the agent's git history).
_DEFAULT_RESUME_DIR: Path = REPO_ROOT / "resumes"


# Relative paths resolve against the repo root (not the current directory), so
# `RESUME_SOURCE_DIR=./resumes` means the same thing from any working dir.
def _repo_path(raw: str | None, default: Path) -> Path:
    p = Path(raw).expanduser() if raw else default
    return (p if p.is_absolute() else REPO_ROOT / p).resolve()


RESUME_SOURCE_DIR: Path = _repo_path(os.environ.get("RESUME_SOURCE_DIR"), _DEFAULT_RESUME_DIR)

DB_PATH: Path = _repo_path(os.environ.get("APPLY_AGENT_DB"), REPO_ROOT / "apply_agent.db")
MASTER_KEY_PATH: Path = SECRETS_DIR / "master.age.key"
PROFILE_ENC_PATH: Path = SECRETS_DIR / "profile.yaml.age"
PASSWORDS_CSV_PATH: Path = SECRETS_DIR / "portal_passwords.csv"


def _int_env(name: str, default: int, *, lo: int, hi: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError:
        raise SystemExit(f"{name}={raw!r} must be an integer") from None
    if not lo <= val <= hi:
        raise SystemExit(f"{name}={val} must be between {lo} and {hi}")
    return val


def _tz_env() -> ZoneInfo:
    name = os.environ.get("APPLY_TIMEZONE") or "America/Chicago"
    try:
        return ZoneInfo(name)
    except Exception:
        raise SystemExit(f"APPLY_TIMEZONE={name!r} is not a valid IANA timezone") from None


# --- volume & timing guardrails (docs/SPEC.md §6) -------------------------
# Tunable DOWNWARD only: the 25/day hard cap can be lowered, never raised.
LOCAL_TZ: ZoneInfo = _tz_env()
SUBMIT_WINDOW_START: int = _int_env("SUBMIT_WINDOW_START", 10, lo=0, hi=23)
SUBMIT_WINDOW_END: int = _int_env("SUBMIT_WINDOW_END", 18, lo=1, hi=24)
DAILY_CAP: int = _int_env("DAILY_CAP", 25, lo=1, hi=25)
COOLDOWN_DAYS: int = _int_env("COOLDOWN_DAYS", 90, lo=30, hi=3650)
# Run the browser without a window (Docker / servers). Tier-3 takeover needs a
# visible window, so leave this off on a desktop.
HEADLESS: bool = (os.environ.get("APPLY_HEADLESS") or "").strip().lower() in ("1", "true", "yes")
if SUBMIT_WINDOW_START >= SUBMIT_WINDOW_END:
    raise SystemExit("SUBMIT_WINDOW_START must be earlier than SUBMIT_WINDOW_END")


@dataclass
class Settings:
    """Resolved runtime settings. Built once in main.py; passed explicitly."""

    # --- flags ---
    dry_run: bool = True  # safety default — keep ON until you've verified a dry run
    no_telegram: bool = False
    ping_only: bool = False

    # --- credentials (may be missing; modules degrade gracefully) ---
    gemini_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None  # allowlisted recipient
    inbox_user: str | None = None
    inbox_password: str | None = None
    inbox_imap_host: str = "imap.gmx.com"
    inbox_imap_port: int = 993

    # --- derived/loaded ---
    repo_root: Path = field(default_factory=lambda: REPO_ROOT)
    db_path: Path = field(default_factory=lambda: DB_PATH)
    master_key_path: Path = field(default_factory=lambda: MASTER_KEY_PATH)
    profile_enc_path: Path = field(default_factory=lambda: PROFILE_ENC_PATH)
    passwords_csv_path: Path = field(default_factory=lambda: PASSWORDS_CSV_PATH)
    resume_source_dir: Path = field(default_factory=lambda: RESUME_SOURCE_DIR)

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID") or None,
            inbox_user=os.environ.get("APPLY_EMAIL_USER") or None,
            inbox_password=os.environ.get("APPLY_EMAIL_PASSWORD") or None,
            inbox_imap_host=os.environ.get("APPLY_EMAIL_IMAP_HOST") or "imap.gmx.com",
            inbox_imap_port=_int_env("APPLY_EMAIL_IMAP_PORT", 993, lo=1, hi=65535),
        )

    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    def inbox_configured(self) -> bool:
        return bool(self.inbox_user and self.inbox_password)
