"""chat_id allowlist. Single source of truth: env TELEGRAM_CHAT_ID.

Currently a single chat_id check. Can be expanded to a comma-separated
allowlist with a `@require_allowlist` decorator if you need multiple users.
"""

from __future__ import annotations


def is_allowed(chat_id: int | str, expected: str | None) -> bool:
    if not expected:
        return False
    return str(chat_id) == str(expected).strip()
