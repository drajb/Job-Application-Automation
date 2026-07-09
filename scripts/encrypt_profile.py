"""One-shot helper: read plaintext secrets/profile.yaml, encrypt to secrets/profile.yaml.age, delete plaintext.

Usage:
    python -m scripts.encrypt_profile

Reads the master key from secrets/master.age.key (generate with `age-keygen -o ...`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pyrage

from src.config import MASTER_KEY_PATH, PROFILE_ENC_PATH, SECRETS_DIR


def main() -> int:
    plaintext = SECRETS_DIR / "profile.yaml"
    if not plaintext.exists():
        print(f"ERROR: {plaintext} not found. Copy .env.example-style template first.", file=sys.stderr)
        return 1
    if not MASTER_KEY_PATH.exists():
        print(f"ERROR: {MASTER_KEY_PATH} missing. Run: age-keygen -o {MASTER_KEY_PATH}", file=sys.stderr)
        return 1

    identity = pyrage.x25519.Identity.from_str(_extract_secret_key(MASTER_KEY_PATH))
    recipient = identity.to_public()

    data = plaintext.read_bytes()
    encrypted = pyrage.encrypt(data, [recipient])
    PROFILE_ENC_PATH.write_bytes(encrypted)
    plaintext.unlink()  # remove plaintext after successful encrypt
    print(f"encrypted → {PROFILE_ENC_PATH}; plaintext deleted")
    return 0


def _extract_secret_key(key_path: Path) -> str:
    for line in key_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("AGE-SECRET-KEY-"):
            return line
    raise RuntimeError(f"no AGE-SECRET-KEY- line in {key_path}")


if __name__ == "__main__":
    sys.exit(main())
