"""Portal account creation + verification flow.

ensure_account(portal_domain, application_id) returns Credentials. It:
  1. If vault has creds for this domain, return them.
  2. Otherwise:
     a) generate a fresh 24-char password
     b) create an email_expectation for the verify link
     c) drive the portal's signup form via Tier-2 (browser-use)
     d) wait for the verify email; click the link
     e) store credentials in the vault (which mirrors to CSV)

Per docs/SPEC.md §7.2.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from src.accounts.password_gen import generate_password
from src.accounts.vault import Credentials, Vault
from src.config import Settings
from src.email_monitor.signup_correlator import (
    create_expectation,
    wait_for_fulfillment,
)
from src.profile.loader import load as load_profile
from src.util.time import utcnow

log = logging.getLogger(__name__)


async def ensure_account(
    *,
    portal_url: str,
    application_id: int,
    vault: Vault,
    settings: Settings,
) -> Credentials:
    domain = urlparse(portal_url).netloc.lower()
    existing = vault.get(domain)
    if existing is not None:
        log.info("vault hit for %s", domain)
        return existing

    profile = load_profile()
    email = str(profile.identity.email)
    password = generate_password(24)
    creds = Credentials(portal_domain=domain, username=email, password=password)

    sender_root = _root_domain(domain)
    expectation_id = create_expectation(
        application_id=application_id,
        expected_sender_domain=sender_root,
        purpose="verify_email",
        expected_subject_regex=r"(verify|confirm|activate).*(email|account)",
        ttl_seconds=600,
    )
    log.info("account signup: created expectation #%s for %s", expectation_id, sender_root)

    # Drive the signup form via Tier-2. The task is generic — fill the form.
    from src.execution.tier2_browseruse import run_tier2
    task = (
        f"Sign up for an account at {portal_url} using:\n"
        f"  email: {email}\n  password: {password}\n  first/last: {profile.identity.legal_name}\n"
        f"Submit the form. Do NOT proceed past signup confirmation."
    )
    result = await run_tier2(url=portal_url, task=task, settings=settings, max_steps=30)
    log.info("tier2 signup result: %s", result.get("status"))

    # Wait for the verify email.
    fulfilled_link = await wait_for_fulfillment(expectation_id, timeout_seconds=600)
    if fulfilled_link is None:
        raise RuntimeError(
            f"signup verify email did not arrive for {domain} within timeout. "
            f"Use /handoff to finish manually.",
        )

    # Hit the verify link in a Tier-2 micro-task.
    confirm_task = f"Open {fulfilled_link} and confirm the account. Done when the page says confirmed/verified."
    await run_tier2(url=fulfilled_link, task=confirm_task, settings=settings, max_steps=10)

    # Mark verified.
    vault.store(
        creds,
        display_name=domain,
        portal_url=portal_url,
        verified=True,
    )
    log.info("account ready: %s (verified at %s)", domain, utcnow().isoformat())
    return creds


def _root_domain(host: str) -> str:
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    return ".".join(parts[-2:])
