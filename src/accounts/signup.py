"""Portal account creation + verification flow (docs/SPEC.md §7.2).

ensure_account(page, portal_url, ...) returns Credentials:
  1. If the vault already has creds for this portal, return them.
  2. Otherwise:
     a) generate a fresh 24-char password and store it in the vault FIRST
        (verified=False) — if anything later fails, the account that may now
        exist on the portal is never orphaned without its password;
     b) drive the portal's sign-up form with the Tier-2 loop. The password is
        NEVER sent to the LLM: the model writes the placeholder {{PASSWORD}}
        and the executor substitutes it locally;
     c) wait for the verification email (sender domain + DKIM + link host are
        checked by the signup correlator), open the link in the same page;
     d) mark the credentials verified (the vault mirrors to the CSV).

Only runs for real (non-dry-run) applications — creating an account is a
real-world side effect.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from src.accounts.password_gen import generate_password
from src.accounts.vault import Credentials, Vault
from src.config import Settings
from src.email_monitor.signup_correlator import (
    create_expectation,
    refresh_expectation,
    registrable_domain,
    wait_for_fulfillment,
)
from src.util.time import utcnow

log = logging.getLogger(__name__)

VERIFY_TIMEOUT_S = 600


class SignupError(RuntimeError):
    pass


def portal_key(portal_url: str) -> str:
    """Vault key for a portal: its hostname (tenant-specific for Workday etc.)."""
    return (urlparse(portal_url).hostname or "").lower()


async def ensure_account(
    *,
    page,
    portal_url: str,
    application_id: int,
    vault: Vault,
    settings: Settings,
    email: str,
    full_name: str,
) -> Credentials:
    domain = portal_key(portal_url)
    existing = vault.get(domain)
    if existing is not None:
        log.info("vault hit for %s", domain)
        return existing

    password = generate_password(24)
    creds = Credentials(portal_domain=domain, username=email, password=password, email_used=email)
    vault.store(creds, display_name=domain, portal_url=portal_url, verified=False)

    sender_root = registrable_domain(domain)
    expectation_id = create_expectation(
        application_id=application_id,
        expected_sender_domain=sender_root,
        purpose="verify_email",
        expected_subject_regex=r"(verif|confirm|activat|welcome)",
        ttl_seconds=VERIFY_TIMEOUT_S * 2,
    )
    log.info("account signup: expectation #%s for %s", expectation_id, sender_root)

    from src.execution.tier2_browseruse import run_tier2

    task = (
        f"Create a new candidate account on this careers site.\n"
        f"  email: {{{{EMAIL}}}}\n  password: {{{{PASSWORD}}}} (type exactly this placeholder; "
        f"it is replaced with the real password locally)\n  name: {full_name}\n"
        f"Click the create-account / register button yourself. Accept only the required "
        f"terms checkbox. When the site says to check your email, return type=ready."
    )
    result = await run_tier2(
        page=page, url=portal_url, task=task, settings=settings,
        resume_pdf=None, max_steps=30, allow_submit=True,
        secrets={"{{EMAIL}}": email, "{{PASSWORD}}": password},
    )
    if result.get("status") != "ready":
        raise SignupError(f"sign-up form not completed ({result.get('status')}) — finish it manually")

    # The verify window starts now, not before the (slow) sign-up form.
    refresh_expectation(expectation_id, ttl_seconds=VERIFY_TIMEOUT_S)
    link = await wait_for_fulfillment(expectation_id, timeout_seconds=VERIFY_TIMEOUT_S)
    if not link:
        raise SignupError(
            f"verification email from {sender_root} did not arrive within "
            f"{VERIFY_TIMEOUT_S // 60} min. The password is saved in the vault — "
            f"verify manually, then retry.",
        )

    await page.goto(link, wait_until="domcontentloaded", timeout=30_000)
    vault.store(creds, display_name=domain, portal_url=portal_url, verified=True)
    log.info("account ready: %s (verified at %s)", domain, utcnow().isoformat())
    await page.goto(portal_url, wait_until="domcontentloaded", timeout=30_000)
    return creds
