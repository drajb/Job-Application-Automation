"""Approval / pause / response-alert / discovery card layouts.

Cards are rendered with Telegram's HTML parse mode. Every interpolated value
goes through `_e()` (html.escape) — the fixed text needs no escaping, which
is why we don't use MarkdownV2 (where a stray '#', '.', or '-' in the fixed
text makes Telegram reject the whole message).
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

_MAX = 3900  # Telegram hard limit is 4096; leave headroom for markup


@dataclass
class Card:
    text: str
    reply_markup: InlineKeyboardMarkup | None = None


def _e(s: object) -> str:
    return html.escape(str(s if s is not None else ""), quote=False)


def _clip(text: str) -> str:
    return text if len(text) <= _MAX else text[: _MAX - 1] + "…"


def approval_card(
    *,
    app_id: int,
    company: str,
    role: str,
    ats: str,
    tier: str,
    resume_name: str,
    variant: str,
    resume_uuid: str,
    validator_ok: bool,
    diffs: list[tuple[str, str]] | None = None,
    fit_percent: int | None = None,
    missing_keywords: list[str] | None = None,
    dry_run: bool = True,
    warnings: list[str] | None = None,
) -> Card:
    lines = [
        f"🎯 <b>{_e(company)} — {_e(role)}</b>",
        f"ATS: {_e(ats)} · {_e(tier)} · app #{app_id}",
        f"Resume: <code>{_e(resume_name)}</code> (variant <code>{_e(variant)}</code>)",
        f"UUID: <code>{_e(resume_uuid)}</code>",
        f"Validator: {'✅ every fact traced to your resume' if validator_ok else '⚠️ WARN'}",
    ]
    if fit_percent is not None:
        lines.append(f"Fit: <b>{fit_percent}%</b>")
    if missing_keywords:
        lines.append(f"JD keywords not in your resume: {_e(', '.join(missing_keywords[:8]))}")
    for w in warnings or []:
        lines.append(f"⚠️ {_e(w)}")
    if diffs:
        lines.append("\n<b>Tailored bullets</b>")
        for before, after in diffs[:5]:
            if before.strip() == after.strip():
                continue
            lines.append(f"• <s>{_e(before[:220])}</s>\n  → {_e(after[:220])}")
    lines.append(
        "\n🧪 DRY RUN — approving will NOT submit." if dry_run else
        "\n🚀 LIVE — approving clicks Submit.",
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Submit" if not dry_run else "✅ Looks good",
                             callback_data=f"approve:{app_id}"),
        InlineKeyboardButton("✗ Reject", callback_data=f"reject:{app_id}"),
    ], [
        InlineKeyboardButton("🖥 Take over", callback_data=f"handoff:{app_id}"),
    ]])
    return Card(text=_clip("\n".join(lines)), reply_markup=kb)


def pause_card(app_id: int, question: str) -> Card:
    text = (
        f"🤔 <b>Question — app #{app_id}</b>\n\n"
        f"{_e(question)}\n\n"
        f"<i>Reply to this message with the answer.</i> I'll remember it for next time."
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⏭ Skip", callback_data=f"skip:{app_id}"),
        InlineKeyboardButton("🖥 Take over", callback_data=f"handoff:{app_id}"),
        InlineKeyboardButton("🛑 Abort", callback_data=f"abort:{app_id}"),
    ]])
    return Card(text=_clip(text), reply_markup=kb)


def response_alert_card(
    application_id: int | None,
    company: str,
    role: str,
    days_ago: int | None,
    from_addr: str,
    subject: str,
    body_excerpt: str,
    category: str,
    resume_variant: str | None = None,
) -> Card:
    icon = {
        "interview_invite": "📬 INTERVIEW",
        "recruiter_outreach": "💼 RECRUITER",
        "offer": "🎉 OFFER",
    }.get(category, "📨 RESPONSE")
    ctx = f"applied {days_ago}d ago · app #{application_id}" if application_id else "no matching application"
    if resume_variant:
        ctx += f" · resume <code>{_e(resume_variant)}</code>"
    text = (
        f"<b>{icon} — {_e(company)} ({_e(role)})</b>\n"
        f"{ctx}\n\n"
        f"<b>From:</b> {_e(from_addr)}\n"
        f"<b>Subject:</b> {_e(subject)}\n\n"
        f"{_e(body_excerpt[:600])}"
    )
    return Card(text=_clip(text))


def status_card(
    *, today: int, week: int, rpd_used: int, rpd_cap: int,
    pending: int = 0, responses_week: int = 0, interviews_week: int = 0,
) -> Card:
    text = (
        "📊 <b>apply-agent status</b>\n\n"
        f"Submitted today: <b>{today}</b>\n"
        f"Submitted this week: <b>{week}</b>\n"
        f"Awaiting you: <b>{pending}</b>\n"
        f"Responses this week: <b>{responses_week}</b> (interviews/offers: {interviews_week})\n"
        f"Gemini requests today: <b>{rpd_used}</b> / {rpd_cap}\n"
    )
    return Card(text=text)


def discovered_job_card(
    *, job_id: int, company: str, title: str, location: str, url: str,
    fit_percent: int, missing: list[str], remote: bool = False,
) -> Card:
    where = location or ("Remote" if remote else "—")
    lines = [
        f"🔎 <b>{_e(company)} — {_e(title)}</b>",
        f"{_e(where)}{' · remote' if remote and 'remote' not in where.lower() else ''}",
        f"Fit: <b>{fit_percent}%</b>",
    ]
    if missing:
        lines.append(f"Missing: {_e(', '.join(missing[:6]))}")
    lines.append(f'<a href="{html.escape(url, quote=True)}">View posting</a>')
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 Apply", callback_data=f"jobapply:{job_id}"),
        InlineKeyboardButton("🙈 Skip", callback_data=f"jobskip:{job_id}"),
    ]])
    return Card(text=_clip("\n".join(lines)), reply_markup=kb)
