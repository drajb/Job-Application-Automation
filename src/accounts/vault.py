"""Encrypted credential vault. Mirrors docs/SPEC.md §7.2 and §7.7.

- get/store/delete: row-level age encryption with the master key.
- export_csv(): regenerates secrets/portal_passwords.csv after every write.
  CSV is one-way: vault → CSV. Edits to the CSV are NOT read back.

The master key is loaded once at process start (Vault.open()) and kept in
memory only. Do not log the key or any decrypted password.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

import pyrage
from sqlalchemy import select

from src.config import MASTER_KEY_PATH, PASSWORDS_CSV_PATH, SECRETS_DIR
from src.db.models import PortalCredential
from src.db.session import get_session
from src.util.time import utcnow

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Credentials:
    portal_domain: str
    username: str | None
    password: str
    email_used: str = ""
    notes: str | None = None


class VaultLockedError(RuntimeError):
    """Raised when vault operations are attempted before Vault.open()."""


class Vault:
    """In-memory keyholder. Construct via Vault.open() at process start."""

    def __init__(self, identity: pyrage.x25519.Identity) -> None:
        self._identity = identity
        self._recipient = identity.to_public()

    # --- lifecycle ---------------------------------------------------------

    @classmethod
    def open(cls, key_path: Path = MASTER_KEY_PATH) -> Vault:
        if not key_path.exists():
            raise VaultLockedError(
                f"master key missing: {key_path}. Run `make keygen` to create one. "
                f"Back up the key file — losing it = losing every portal password.",
            )
        secret_line = _read_secret(key_path)
        identity = pyrage.x25519.Identity.from_str(secret_line)
        log.info("vault opened (master key at %s)", key_path)
        return cls(identity)

    # --- crud --------------------------------------------------------------

    def store(
        self,
        creds: Credentials,
        *,
        display_name: str | None = None,
        portal_url: str | None = None,
        verified: bool = False,
    ) -> None:
        ciphertext = pyrage.encrypt(creds.password.encode("utf-8"), [self._recipient])
        with get_session() as s:
            row = s.scalar(
                select(PortalCredential).where(
                    PortalCredential.portal_domain == creds.portal_domain,
                ),
            )
            now = utcnow()
            if row is None:
                row = PortalCredential(
                    portal_domain=creds.portal_domain,
                    username=creds.username,
                    password_enc=ciphertext,
                    email_used=creds.email_used,
                    signup_date=now,
                    last_used=now,
                    verified=verified,
                    display_name=display_name,
                    portal_url=portal_url,
                    notes=creds.notes,
                )
                s.add(row)
            else:
                row.username = creds.username
                row.password_enc = ciphertext
                row.email_used = creds.email_used
                row.last_used = now
                row.verified = verified
                if display_name:
                    row.display_name = display_name
                if portal_url:
                    row.portal_url = portal_url
                if creds.notes is not None:
                    row.notes = creds.notes
            s.commit()
        self.export_csv()

    def get(self, portal_domain: str) -> Credentials | None:
        with get_session() as s:
            row = s.scalar(
                select(PortalCredential).where(
                    PortalCredential.portal_domain == portal_domain,
                ),
            )
            if row is None:
                return None
            password = pyrage.decrypt(row.password_enc, [self._identity]).decode("utf-8")
            return Credentials(
                portal_domain=row.portal_domain,
                username=row.username,
                password=password,
                email_used=row.email_used,
                notes=row.notes,
            )

    def delete(self, portal_domain: str) -> bool:
        with get_session() as s:
            row = s.scalar(
                select(PortalCredential).where(
                    PortalCredential.portal_domain == portal_domain,
                ),
            )
            if row is None:
                return False
            s.delete(row)
            s.commit()
        self.export_csv()
        return True

    # --- csv mirror --------------------------------------------------------

    def export_csv(self, path: Path = PASSWORDS_CSV_PATH) -> Path:
        SECRETS_DIR.mkdir(parents=True, exist_ok=True)
        with get_session() as s, path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                [
                    "portal_domain",
                    "display_name",
                    "portal_url",
                    "username",
                    "password",
                    "email_used",
                    "signup_date",
                    "last_used",
                    "verified",
                    "notes",
                ],
            )
            for row in s.scalars(select(PortalCredential).order_by(PortalCredential.portal_domain)):
                try:
                    password = pyrage.decrypt(row.password_enc, [self._identity]).decode("utf-8")
                except Exception as e:
                    log.error(
                        "vault: decrypt failed for portal=%s (wrong master key?): %s",
                        row.portal_domain, e,
                    )
                    password = "<DECRYPT_FAILED>"
                writer.writerow(
                    [
                        row.portal_domain,
                        row.display_name or "",
                        row.portal_url or "",
                        row.username or "",
                        password,
                        row.email_used,
                        row.signup_date.isoformat() if row.signup_date else "",
                        row.last_used.isoformat() if row.last_used else "",
                        "1" if row.verified else "0",
                        row.notes or "",
                    ],
                )
        log.info("password CSV mirror regenerated: %s", path)
        return path


def _read_secret(key_path: Path) -> str:
    for line in key_path.read_text().splitlines():
        s = line.strip()
        if s.startswith("AGE-SECRET-KEY-"):
            return s
    raise VaultLockedError(f"{key_path}: no AGE-SECRET-KEY- line found")
