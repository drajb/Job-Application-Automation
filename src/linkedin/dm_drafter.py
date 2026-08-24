"""Draft a referral / outreach DM. We never send it — the user pastes it themselves.

Uses Gemini Flash for personalization. Truthfulness contract still applies: no
fabricated shared history. The prompt enforces this.
"""

from __future__ import annotations

import logging

from src.config import Settings
from src.linkedin.referral_scan import Candidate
from src.llm.client import GeminiClient

log = logging.getLogger(__name__)


_PROMPT = """Draft a SHORT (60-110 word) LinkedIn DM to ask {target_name} for a referral or
quick conversation about a role at {company}.

# About me (use only what's here; do not invent past interactions)
- name: {my_name}
- current role: AI engineer building agentic systems
- target role: {role} at {company}
- common ground (if any): {common_ground}

# Their headline (verbatim)
{their_headline}

# Rules
- Sound human, direct. No "Dear", no "Hope this finds you well".
- Mention ONE specific thing about their role/company that's verifiable from
  their headline. Do not assume mutual connections.
- End with a single clear ask (15-min chat OR a referral, pick one).
- 110 words MAX.

# Output
The DM text only. No preamble.
"""


async def draft(
    *,
    candidate: Candidate,
    company: str,
    role: str,
    my_name: str,
    common_ground: str = "(none)",
    settings: Settings,
    client: GeminiClient | None = None,
) -> str:
    if client is None:
        client = GeminiClient(settings)
    return await client.generate(
        _PROMPT.format(
            target_name=candidate.name.split()[0] if candidate.name else "there",
            company=company, role=role,
            my_name=my_name,
            common_ground=common_ground,
            their_headline=candidate.headline,
        ),
        temperature=0.4,
        max_output_tokens=400,
    )
