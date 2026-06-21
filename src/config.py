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

# Repo root (apply-agent/), resolved from this file's location.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
SECRETS_DIR: Path = REPO_ROOT / "secrets"
DATA_DIR: Path = REPO_ROOT / "data"

# Default resume source directory. Override with RESUME_SOURCE_DIR env var if
# your resumes live outside the repo (recommended — keeps your private CV out
# of the agent's git history).
_DEFAULT_RESUME_DIR: Path = REPO_ROOT / "resumes"
RESUME_SOURCE_DIR: Path = Path(
    os.environ.get("RESUME_SOURCE_DIR") or _DEFAULT_RESUME_DIR
).expanduser().resolve()

DB_PATH: Path = REPO_ROOT / "apply_agent.db"
MASTER_KEY_PATH: Path = SECRETS_DIR / "master.age.key"
PROFILE_ENC_PATH: Path = SECRETS_DIR / "profile.yaml.age"
PASSWORDS_CSV_PATH: Path = SECRETS_DIR / "portal_passwords.csv"


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
            inbox_imap_port=int(os.environ.get("APPLY_EMAIL_IMAP_PORT") or "993"),
        )

    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    def inbox_configured(self) -> bool:
        return bool(self.inbox_user and self.inbox_password)
