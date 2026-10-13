"""Gemini 2.5 Flash wrapper (google-genai SDK). Single entry point so the rate
limiter sees every call.

NEVER add any other provider. Per Hard Rules: Gemini only.

Robustness:
  - Transient API errors (429 / 500 / 503 / timeouts) are retried with
    exponential backoff; every retry goes back through the rate limiter.
  - A response that was blocked or cut off (finish_reason != STOP) raises
    GeminiIncomplete instead of silently returning partial text — a truncated
    resume must never reach the renderer.
  - "Thinking" is off by default (thinking_budget=0): our calls are rewrite /
    extract / classify tasks, and thinking tokens count against the output cap.
"""

from __future__ import annotations

import asyncio
import logging

from src.config import Settings
from src.llm.rate_limiter import RateLimiter, get_rate_limiter

log = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"
_MAX_ATTEMPTS = 3
_OK_FINISH = {"STOP", "FINISH_REASON_UNSPECIFIED", "None"}


class GeminiIncomplete(RuntimeError):
    """The model stopped early (token limit, safety block, recitation...)."""


def _is_transient(e: Exception) -> bool:
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if code in (408, 429, 500, 502, 503, 504):
        return True
    name = type(e).__name__
    if name in {"ServerError", "ResourceExhausted", "ServiceUnavailable", "DeadlineExceeded",
                "ReadTimeout", "ConnectTimeout", "ConnectError", "RemoteProtocolError"}:
        return True
    msg = str(e)
    return any(s in msg for s in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "timed out"))


def extract_text(resp) -> str:
    """Return the full text of a generate_content response, or raise
    GeminiIncomplete with the reason."""
    candidates = getattr(resp, "candidates", None) or []
    if not candidates:
        feedback = getattr(resp, "prompt_feedback", None)
        raise GeminiIncomplete(f"no candidates returned (prompt_feedback={feedback})")
    cand = candidates[0]
    reason = getattr(cand, "finish_reason", None)
    reason_name = getattr(reason, "name", None) or str(reason)
    if reason_name not in _OK_FINISH:
        raise GeminiIncomplete(f"generation stopped early: finish_reason={reason_name}")
    parts = getattr(getattr(cand, "content", None), "parts", None) or []
    return "".join(
        (getattr(p, "text", "") or "") for p in parts if not getattr(p, "thought", False)
    )


class GeminiClient:
    def __init__(self, settings: Settings, limiter: RateLimiter | None = None) -> None:
        if not settings.gemini_configured():
            raise RuntimeError(
                "GEMINI_API_KEY missing — set it in .env. "
                "Get a free key at https://aistudio.google.com/apikey",
            )
        from google import genai

        self._client = genai.Client(api_key=settings.gemini_api_key)
        # Default to the process singleton so RPM/RPD are shared across every
        # caller. A caller may inject its own limiter (tests do).
        self._limiter = limiter or get_rate_limiter()

    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.3,
        max_output_tokens: int = 8192,
        json_mode: bool = False,
        priority: bool = False,
        thinking_budget: int = 0,
    ) -> str:
        """One completion. `priority=True` may use the last 5% of the daily
        budget (email classification, signup verification)."""
        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json" if json_mode else None,
            thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
        )

        delay = 2.0
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            await self._limiter.acquire(priority=priority)
            try:
                resp = await self._client.aio.models.generate_content(
                    model=MODEL_NAME, contents=prompt, config=config,
                )
                out = extract_text(resp)
            except GeminiIncomplete:
                raise
            except Exception as e:
                if attempt < _MAX_ATTEMPTS and _is_transient(e):
                    log.warning("gemini transient error (attempt %d): %s — retrying in %.0fs",
                                attempt, e, delay)
                    await asyncio.sleep(delay)
                    delay *= 3
                    continue
                log.error("gemini call failed: %s", e)
                raise
            self._limiter.record_success(approx_tokens=len(prompt) // 4 + len(out) // 4)
            return out
        raise RuntimeError("unreachable")  # pragma: no cover
