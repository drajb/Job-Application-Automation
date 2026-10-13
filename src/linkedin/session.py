"""Reuse a saved LinkedIn login session for read-only browsing.

The agent never logs in to LinkedIn itself. Instead, you log in once via a
real browser (or `scripts/save_linkedin_session.py` — see docs/LINKEDIN.md)
and save Playwright's `storage_state.json` to a known location. The referral
scanner and Tier-3 takeover read that file and reuse the cookies.

Default lookup path: `secrets/linkedin/storage_state.json`.
Override with the `LINKEDIN_SESSION_PATH` env var if you keep it elsewhere.

We piggyback on a saved storage state rather than re-implementing login so
we don't have to handle LinkedIn's 2FA / captcha flow in code.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from src.config import REPO_ROOT

log = logging.getLogger(__name__)


def _resolve_default() -> Path:
    """Default session-file location, env-overridable."""
    env = os.environ.get("LINKEDIN_SESSION_PATH")
    if env:
        return Path(env).expanduser().resolve()
    return REPO_ROOT / "secrets" / "linkedin" / "storage_state.json"


SESSION_PATH: Path = _resolve_default()


def has_session() -> bool:
    if not SESSION_PATH.exists():
        return False
    try:
        data = json.loads(SESSION_PATH.read_text())
        return any(c.get("name") == "li_at" for c in data.get("cookies", []))
    except Exception as e:
        log.debug("could not parse LinkedIn session at %s: %s", SESSION_PATH, e)
        return False


def session_path() -> Path:
    return SESSION_PATH
