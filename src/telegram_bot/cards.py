"""Approval / handoff / response-alert card layouts.

Telegram supports Markdown V2 with InlineKeyboardMarkup. We keep cards short
because they render in a phone notification preview.
"""

from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.ats.base import ParsedJob
from src.resume.renderer import RenderResult
from src.resume.validator import ValidationResult


@dataclass
class Card:
    text: str
    reply_markup: InlineKeyboardMarkup | None = None


def approval_card(
    app_id: int,
    job: ParsedJob,
    variant: str,
    rendered: RenderResult,
    validation: ValidationResult,
) -> Card:
    text = (
        f"*Approval needed — app #{app_id}*\n\n"
        f"*Company:* {_esc(job.company)}\n"
        f"*Role:* {_esc(job.role)}\n"
        f"*ATS:* {_esc('greenhouse')}  *Tier:* 1\n"
        f"*Resume:* `{rendered.pdf_path.name}`\n"
        f"*Variant:* `{variant}`\n"
        f"*UUID:* `{rendered.uuid}`\n"
        f"*Validator:* {'OK' if validation.ok else 'WARN'}\n"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Submit", callback_data=f"approve:{app_id}"),
            InlineKeyboardButton("Reject", callback_data=f"reject:{app_id}"),
        ],
        [
            InlineKeyboardButton("Screenshot", callback_data=f"shot:{app_id}"),
            InlineKeyboardButton("Edit", callback_data=f"edit:{app_id}"),
        ],
    ])
    return Card(text=text, reply_markup=kb)


def pause_card(app_id: int, question: str) -> Card:
    text = (
        f"*Stuck — app #{app_id}*\n\n"
        f"*Question:* {_esc(question)}\n\n"
        f"Reply to this message with the answer, or hit Takeover to drive."
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Takeover", callback_data=f"handoff:{app_id}"),
            InlineKeyboardButton("Abort", callback_data=f"abort:{app_id}"),
        ],
    ])
    return Card(text=text, reply_markup=kb)


def response_alert_card(
    application_id: int,
    company: str,
    role: str,
    days_ago: int,
    from_addr: str,
    subject: str,
    body_excerpt: str,
    category: str,
) -> Card:
    icon = {
        "interview_invite": "📬 INTERVIEW",
        "recruiter_outreach": "💼 RECRUITER",
        "offer": "🎉 OFFER",
    }.get(category, "📨 RESPONSE")
    text = (
        f"*{icon} — {_esc(company)} ({_esc(role)})*\n"
        f"applied {days_ago}d ago · app #{application_id}\n\n"
        f"*From:* {_esc(from_addr)}\n"
        f"*Subject:* {_esc(subject)}\n\n"
        f"{_esc(body_excerpt[:600])}"
    )
    return Card(text=text)


def status_card(today: int, week: int, rpd_used: int, rpd_cap: int) -> Card:
    text = (
        f"*apply-agent status*\n\n"
        f"Today: *{today}* submissions\n"
        f"This week: *{week}*\n"
        f"Gemini RPD: *{rpd_used}* / {rpd_cap}\n"
    )
    return Card(text=text)


def _esc(s: str) -> str:
    """Escape Markdown V2 special chars."""
    for ch in r"_*[]()~`>#+-=|{}.!":
        s = s.replace(ch, "\\" + ch)
    return s
