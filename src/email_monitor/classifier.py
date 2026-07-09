"""Classify response emails into 6 categories via Gemini Flash.

Categories:
  interview_invite | recruiter_outreach | offer | rejection | confirmation | other

Per docs/SPEC.md §7.3:
  - interview_invite / recruiter_outreach / offer → immediate Telegram alert
  - confirmation → silent log
  - rejection → silent log + daily digest
  - other → daily digest
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

from src.config import Settings
from src.email_monitor.imap_idle import IncomingEmail
from src.llm.client import GeminiClient

log = logging.getLogger(__name__)

Category = Literal[
    "interview_invite", "recruiter_outreach", "offer",
    "rejection", "confirmation", "other",
]
HIGH_PRIORITY: set[Category] = {"interview_invite", "recruiter_outreach", "offer"}


@dataclass
class Classification:
    category: Category
    confidence: float
    one_line_summary: str


_PROMPT = """Classify the following job-application response email.

Email from: {from_addr}
Subject: {subject}

Body (first 2000 chars):
{body}

Return JSON, exactly:
{{"category":"<one of: interview_invite|recruiter_outreach|offer|rejection|confirmation|other>",
  "confidence":0.0-1.0,
  "one_line_summary":"<one sentence>"}}

Definitions:
- interview_invite: explicitly inviting the candidate to interview, schedule a call, take an
  assessment, or proceed to a next-round screen.
- recruiter_outreach: a recruiter (not necessarily matched to an existing application) reaching
  out to start a conversation. Even cold outreach counts here.
- offer: extending a job offer or asking for compensation/start-date discussion specifically
  because they are ready to offer.
- rejection: a "no thanks" / "moving forward with other candidates" / "won't be progressing".
- confirmation: an automated "we received your application" or "thanks for applying" message
  with no human action requested.
- other: anything else (newsletters, account verifications, calendar invites without context).
"""


async def classify(
    msg: IncomingEmail, *, settings: Settings, client: GeminiClient | None = None,
) -> Classification:
    if client is None:
        client = GeminiClient(settings)
    body = msg.body_text or msg.body_html or ""
    out = await client.generate(
        _PROMPT.format(
            from_addr=msg.from_addr, subject=msg.subject, body=body[:2000],
        ),
        temperature=0.0, json_mode=True, max_output_tokens=256,
    )
    try:
        d = json.loads(out)
        cat = d.get("category", "other")
        if cat not in {
            "interview_invite", "recruiter_outreach", "offer",
            "rejection", "confirmation", "other",
        }:
            cat = "other"
        return Classification(
            category=cat,
            confidence=float(d.get("confidence", 0.5)),
            one_line_summary=str(d.get("one_line_summary", ""))[:200],
        )
    except Exception as e:
        log.warning("classifier: bad JSON (%s) — defaulting to 'other'", e)
        return Classification(category="other", confidence=0.0, one_line_summary="(parse error)")
