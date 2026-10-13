"""Encrypt / decrypt your profile.

    python -m scripts.encrypt_profile            # secrets/profile.yaml → .age, delete plaintext
    python -m scripts.encrypt_profile --decrypt  # .age → secrets/profile.yaml (to edit it)

The plaintext is validated against the profile schema BEFORE it is encrypted
and deleted, so a typo can't lock you out of a broken profile.

Reads the master key from secrets/master.age.key (create it with `make keygen`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pyrage
import yaml

from src.config import MASTER_KEY_PATH, PROFILE_ENC_PATH, SECRETS_DIR

PLAINTEXT = SECRETS_DIR / "profile.yaml"


def _identity() -> pyrage.x25519.Identity:
    if not MASTER_KEY_PATH.exists():
        raise SystemExit(f"ERROR: {MASTER_KEY_PATH} missing. Run: make keygen")
    return pyrage.x25519.Identity.from_str(_extract_secret_key(MASTER_KEY_PATH))


def encrypt() -> int:
    if not PLAINTEXT.exists():
        print(f"ERROR: {PLAINTEXT} not found. Start from profile.example.yaml:\n"
              f"  cp profile.example.yaml {PLAINTEXT}", file=sys.stderr)
        return 1
    identity = _identity()

    from pydantic import ValidationError

    from src.profile.schema import Profile
    data = PLAINTEXT.read_bytes()
    try:
        Profile.model_validate(yaml.safe_load(data) or {})
    except (yaml.YAMLError, ValidationError) as e:
        print(f"ERROR: {PLAINTEXT} is not a valid profile — nothing was encrypted:\n{e}",
              file=sys.stderr)
        return 1

    PROFILE_ENC_PATH.write_bytes(pyrage.encrypt(data, [identity.to_public()]))
    PLAINTEXT.unlink()
    print(f"encrypted → {PROFILE_ENC_PATH}; plaintext deleted")
    return 0


def decrypt() -> int:
    if not PROFILE_ENC_PATH.exists():
        print(f"ERROR: {PROFILE_ENC_PATH} not found.", file=sys.stderr)
        return 1
    if PLAINTEXT.exists():
        print(f"ERROR: {PLAINTEXT} already exists — edit it, then re-encrypt.", file=sys.stderr)
        return 1
    data = pyrage.decrypt(PROFILE_ENC_PATH.read_bytes(), [_identity()])
    fd = os.open(PLAINTEXT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    print(f"decrypted → {PLAINTEXT}. Edit it, then run `make encrypt-profile`.")
    return 0


def _extract_secret_key(key_path: Path) -> str:
    for line in key_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("AGE-SECRET-KEY-"):
            return line
    raise RuntimeError(f"no AGE-SECRET-KEY- line in {key_path}")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    return decrypt() if "--decrypt" in args else encrypt()


if __name__ == "__main__":
    sys.exit(main())
