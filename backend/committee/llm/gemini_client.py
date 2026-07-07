"""Thin Gemini wrapper shared by every LLM-backed agent (News & Sentiment,
Macro, Contrarian). Forces structured JSON output validated against a
pydantic schema, retries once on a malformed response, and raises a single
well-known exception type when the LLM can't be used at all — callers are
expected to catch `LLMUnavailableError` and degrade to a neutral output
rather than let it crash a trading cycle.
"""

from typing import TypeVar

import google.generativeai as genai
from pydantic import BaseModel, ValidationError

from backend.committee.config import settings

MODEL_NAME = "gemini-1.5-flash"

T = TypeVar("T", bound=BaseModel)

_configured = False


class LLMUnavailableError(RuntimeError):
    """No API key configured, or every attempt returned an unusable response."""


def _ensure_configured() -> None:
    global _configured
    if not settings.gemini_api_key:
        raise LLMUnavailableError("GEMINI_API_KEY is not set")
    if not _configured:
        genai.configure(api_key=settings.gemini_api_key)
        _configured = True


def complete(system: str, user: str, schema: type[T]) -> T:
    _ensure_configured()
    model = genai.GenerativeModel(MODEL_NAME, system_instruction=system)
    generation_config = genai.GenerationConfig(
        response_mime_type="application/json",
        response_schema=schema,
    )

    last_error: Exception | None = None
    for _ in range(2):
        try:
            response = model.generate_content(user, generation_config=generation_config)
            return schema.model_validate_json(response.text)
        except (ValidationError, ValueError) as exc:
            last_error = exc
            continue

    raise LLMUnavailableError(f"Gemini response failed validation twice: {last_error}")
