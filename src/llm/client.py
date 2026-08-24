"""Gemini 2.5 Flash wrapper. Single entry point so rate limiter sees every call.

Free tier (per docs/SPEC.md §11): 15 RPM / 1500 RPD / 1M TPM. Worst-case ~400 RPD.
NEVER add any other provider. Per Hard Rules: Gemini only.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import google.generativeai as genai

from src.config import Settings
from src.llm.rate_limiter import RateLimiter, get_rate_limiter

log = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"


class GeminiClient:
    def __init__(self, settings: Settings, limiter: RateLimiter | None = None) -> None:
        if not settings.gemini_configured():
            raise RuntimeError(
                "GEMINI_API_KEY missing — set it in .env. "
                "Get a free key at https://aistudio.google.com/apikey",
            )
        genai.configure(api_key=settings.gemini_api_key)
        self._model = genai.GenerativeModel(MODEL_NAME)
        # Default to the process singleton so RPM/RPD are shared across every
        # caller. A caller may inject its own limiter (tests do).
        self._limiter = limiter or get_rate_limiter()

    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.3,
        max_output_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        await self._limiter.acquire()
        cfg: dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }
        if json_mode:
            cfg["response_mime_type"] = "application/json"

        def _call() -> str:
            resp = self._model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(**cfg),
            )
            return resp.text or ""

        try:
            out = await asyncio.to_thread(_call)
        except Exception as e:
            log.error("gemini call failed: %s", e)
            raise
        self._limiter.record_success(approx_tokens=len(prompt) // 4 + len(out) // 4)
        return out
