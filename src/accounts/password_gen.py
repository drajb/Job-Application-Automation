"""24-char alphanumeric + symbol passwords, cryptographically random, unique per portal."""

from __future__ import annotations

import secrets as _secrets
import string

_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{};:,.?"


_FIRST = string.ascii_letters + string.digits  # never start with = + - @ (CSV formulas)


def generate_password(length: int = 24) -> str:
    """Random password with at least one lower, upper, digit and symbol (many
    portals require all four)."""
    if length < 12:
        raise ValueError("refuse to generate passwords shorter than 12 chars")
    while True:
        pw = _secrets.choice(_FIRST) + "".join(
            _secrets.choice(_ALPHABET) for _ in range(length - 1)
        )
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw) and any(not c.isalnum() for c in pw)):
            return pw
