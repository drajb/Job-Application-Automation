"""Decrypt secrets/profile.yaml.age with secrets/master.age.key and parse to Profile.

Fail loud and specific. The agent should refuse to run real submissions if the
profile can't be loaded. Importing this module without calling load() is fine.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.config import MASTER_KEY_PATH, PROFILE_ENC_PATH
from src.profile.schema import Profile


class ProfileLoadError(RuntimeError):
    """Raised when the encrypted profile cannot be read or parsed."""


def _read_secret_key(key_path: Path) -> str:
    if not key_path.exists():
        raise ProfileLoadError(
            f"master key missing: {key_path}. Generate with `make keygen` (runs "
            f"age-keygen). Back the file up — losing it = losing the vault.",
        )
    for line in key_path.read_text().splitlines():
        s = line.strip()
        if s.startswith("AGE-SECRET-KEY-"):
            return s
    raise ProfileLoadError(
        f"{key_path} exists but contains no AGE-SECRET-KEY- line. Was it truncated?",
    )


def load(
    enc_path: Path = PROFILE_ENC_PATH,
    key_path: Path = MASTER_KEY_PATH,
) -> Profile:
    """Decrypt + parse profile.yaml.age. Returns a validated Profile."""
    if not enc_path.exists():
        raise ProfileLoadError(
            f"encrypted profile missing: {enc_path}. Create secrets/profile.yaml from "
            f"the template in docs/RUNBOOK.md, then run `make encrypt-profile`.",
        )

    # Import lazily so test collection doesn't require pyrage's native build.
    import pyrage

    secret_line = _read_secret_key(key_path)
    identity = pyrage.x25519.Identity.from_str(secret_line)

    try:
        plaintext = pyrage.decrypt(enc_path.read_bytes(), [identity])
    except Exception as e:  # pyrage raises various FFI errors
        raise ProfileLoadError(f"decryption failed for {enc_path}: {e}") from e

    try:
        data = yaml.safe_load(plaintext)
    except yaml.YAMLError as e:
        raise ProfileLoadError(f"decrypted payload is not valid YAML: {e}") from e

    try:
        return Profile.model_validate(data)
    except Exception as e:  # pydantic.ValidationError
        raise ProfileLoadError(f"profile failed schema validation: {e}") from e
