"""Thin Anthropic wrapper — same `complete(system, user, schema)` interface
as gemini_client.py / openai_client.py, so agents stay provider-agnostic via
llm/router.py. Used for the Contrarian agent specifically: a different lab's
model is likely to disagree for reasons the other agents' providers wouldn't.

Uses `messages.parse()` (structured outputs) rather than JSON-mode-and-hope —
Claude Haiku 4.5 supports it natively.
"""

from typing import TypeVar

import anthropic
from pydantic import BaseModel

from backend.committee.config import ANTHROPIC_MODEL_NAME, settings

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


class LLMUnavailableError(RuntimeError):
    """No API key configured, or every attempt returned an unusable response."""


def _get_client() -> anthropic.Anthropic:
    global _client
    if not settings.anthropic_api_key:
        raise LLMUnavailableError("ANTHROPIC_API_KEY is not set")
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def complete(system: str, user: str, schema: type[T]) -> T:
    client = _get_client()

    last_error: Exception | None = None
    for _ in range(2):
        try:
            response = client.messages.parse(
                model=ANTHROPIC_MODEL_NAME,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
            )
            return response.parsed_output
        except anthropic.APIError as exc:
            last_error = exc
            continue

    raise LLMUnavailableError(f"Anthropic response failed twice: {last_error}")
