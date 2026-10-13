"""Pydantic models for profile.yaml. Mirrors docs/SPEC.md §5.1 exactly.

Never log a populated Profile to a non-DEBUG handler — it contains visa
status, comp expectations, and demographics. Treat the in-memory object
as PII.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, HttpUrl


class Location(BaseModel):
    city: str
    state: str
    country: str = "US"


class Identity(BaseModel):
    legal_name: str
    preferred_name: str | None = None
    email: EmailStr
    phone: str
    location: Location
    linkedin: HttpUrl | None = None
    github: HttpUrl | None = None
    portfolio: HttpUrl | None = None


class WorkAuthorization(BaseModel):
    authorized_us: bool
    requires_sponsorship: bool
    current_status: str  # e.g. H1B, GC, USC
    visa_expiration: date | None = None
    i140_approved: bool = False


class Demographics(BaseModel):
    gender: str | None = None
    race: str | None = None
    hispanic_latino: bool | None = None
    veteran: bool | None = None
    disability: Literal["yes", "no", "prefer_not_to_say"] | None = None
    pronouns: str | None = None


class Compensation(BaseModel):
    desired_base_min: int
    desired_base_target: int
    notice_period_weeks: int = 2
    open_to_relocate: bool | str = False
    open_to_remote: bool = True
    open_to_hybrid: bool = True
    open_to_onsite: bool = True
    earliest_start: date | str | None = None


class Background(BaseModel):
    felony: bool = False
    citizenship: str | None = None
    clearance: str = "none"
    how_did_you_hear_default: str = "LinkedIn"


class Education(BaseModel):
    degree: str
    institution: str
    grad_year: int


class Essays(BaseModel):
    why_company_template: str = ""
    why_role_template: str = ""
    about_me_template: str = ""
    proud_project_template: str = ""


class Profile(BaseModel):
    identity: Identity
    work_authorization: WorkAuthorization
    demographics: Demographics = Field(default_factory=Demographics)
    compensation: Compensation
    background: Background = Field(default_factory=Background)
    education: list[Education] = Field(default_factory=list)
    essays: Essays = Field(default_factory=Essays)
