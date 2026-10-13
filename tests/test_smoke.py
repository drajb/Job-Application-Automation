"""Smoke tests: package imports cleanly and safe defaults hold."""

from __future__ import annotations

from src.accounts.password_gen import generate_password
from src.config import Settings
from src.profile.schema import (
    Background,
    Compensation,
    Demographics,
    Education,
    Essays,
    Identity,
    Location,
    Profile,
    WorkAuthorization,
)
from src.telegram_bot.allowlist import is_allowed


def test_settings_dry_run_default_is_on() -> None:
    s = Settings.from_env()
    assert s.dry_run is True, "real submissions must be OFF by default — safety guarantee"


def test_settings_no_credentials_does_not_crash() -> None:
    # Missing all credentials must still construct cleanly (degrade gracefully).
    s = Settings.from_env()
    assert s.gemini_configured() in {True, False}
    assert s.telegram_configured() in {True, False}
    assert s.inbox_configured() in {True, False}


def test_password_gen_unique_and_long() -> None:
    a = generate_password()
    b = generate_password()
    assert a != b
    assert len(a) == 24


def test_password_gen_rejects_short() -> None:
    import pytest

    with pytest.raises(ValueError):
        generate_password(8)


def test_allowlist_rejects_when_unset() -> None:
    assert is_allowed(123, None) is False
    assert is_allowed(123, "") is False


def test_allowlist_matches_string_and_int() -> None:
    assert is_allowed(123, "123") is True
    assert is_allowed("123", "123") is True
    assert is_allowed(999, "123") is False


def test_profile_schema_accepts_minimal_valid() -> None:
    p = Profile(
        identity=Identity(
            legal_name="Jane Doe",
            email="jane.doe@example.com",
            phone="+1-555-555-0100",
            location=Location(city="Springfield", state="IL"),
        ),
        work_authorization=WorkAuthorization(
            authorized_us=True,
            requires_sponsorship=False,
            current_status="Citizen",
        ),
        demographics=Demographics(),
        compensation=Compensation(desired_base_min=150000, desired_base_target=180000),
        background=Background(),
        education=[Education(degree="B.S.", institution="State University", grad_year=2018)],
        essays=Essays(),
    )
    assert p.identity.location.city == "Springfield"
    assert p.work_authorization.requires_sponsorship is False
