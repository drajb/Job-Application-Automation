"""Tailor a source resume to a JD via Gemini Flash. Always validated. 2-retry hard cap.

Outputs the tailored markdown. The renderer handles md → docx → pdf.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.llm.client import GeminiClient
from src.llm.prompts.tailor import tailor_prompt
from src.resume.validator import ValidationResult, validate

log = logging.getLogger(__name__)


@dataclass
class TailorResult:
    ok: bool
    tailored_md: str
    attempts: int
    validation: ValidationResult


async def tailor(
    *,
    jd: str,
    source_md: str,
    company: str,
    role: str,
    client: GeminiClient,
    profile_known_text: str = "",
    max_attempts: int = 2,
) -> TailorResult:
    """Rewrite source_md to match the JD. Validates each attempt. Returns final result.

    On failure after `max_attempts`, .ok is False. Caller should escalate to Telegram
    rather than ship the result.
    """
    last: ValidationResult | None = None
    last_md = ""
    for attempt in range(1, max_attempts + 1):
        prompt = tailor_prompt(jd=jd, source_resume_md=source_md, company=company, role=role)
        if attempt > 1 and last is not None:
            # Feedback loop: tell the model what tripped the validator.
            prompt += (
                f"\n\n# Prior attempt was REJECTED\n"
                f"The validator flagged these as fabricated (not in source resume): "
                f"{last.new_entities[:8]}. Regenerate WITHOUT those entities. Use only "
                f"facts from the source resume."
            )
        out = await client.generate(prompt, temperature=0.2 if attempt == 1 else 0.05)
        last_md = out
        last = validate(out, source_md, extra_known=profile_known_text)
        if last.ok:
            log.info("tailor ok on attempt %d", attempt)
            return TailorResult(ok=True, tailored_md=out, attempts=attempt, validation=last)
        log.warning(
            "tailor attempt %d REJECTED: %s",
            attempt, last.reason,
        )

    return TailorResult(
        ok=False,
        tailored_md=last_md,
        attempts=max_attempts,
        validation=last or ValidationResult(ok=False, reason="no attempts ran"),
    )
