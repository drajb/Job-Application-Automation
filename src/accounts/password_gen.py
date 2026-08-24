"""24-char alphanumeric + symbol passwords, cryptographically random, unique per portal."""

from __future__ import annotations

import secrets as _secrets
import string

_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{};:,.?"


def generate_password(length: int = 24) -> str:
    if length < 12:
        raise ValueError("refuse to generate passwords shorter than 12 chars")
    return "".join(_secrets.choice(_ALPHABET) for _ in range(length))
