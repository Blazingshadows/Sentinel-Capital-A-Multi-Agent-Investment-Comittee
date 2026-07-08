"""Thin OpenAI wrapper — same `complete(system, user, schema)` interface as
gemini_client.py, so agents stay provider-agnostic via llm/router.py. Uses
JSON mode (not a strict json_schema response_format) because pydantic's
generated schema doesn't always satisfy OpenAI's strict-mode constraints
(every field required, no defaults) without extra massaging; the schema is
instead described in the prompt and validated on receipt, with the same
retry-once-then-degrade pattern as the other providers.
"""

from typing import TypeVar

import openai
from pydantic import BaseModel, ValidationError

from backend.committee.config import OPENAI_MODEL_NAME, settings

T = TypeVar("T", bound=BaseModel)

_client: openai.OpenAI | None = None


class LLMUnavailableError(RuntimeError):
    """No API key configured, or every attempt returned an unusable response."""


def _get_client() -> openai.OpenAI:
    global _client
    if not settings.openai_api_key:
        raise LLMUnavailableError("OPENAI_API_KEY is not set")
    if _client is None:
        _client = openai.OpenAI(api_key=settings.openai_api_key)
    return _client


def complete(system: str, user: str, schema: type[T]) -> T:
    client = _get_client()
    schema_hint = (
        "Respond with a single JSON object and nothing else, matching exactly this JSON schema: "
        f"{schema.model_json_schema()}"
    )

    last_error: Exception | None = None
    for _ in range(2):
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL_NAME,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": f"{system}\n\n{schema_hint}"},
                    {"role": "user", "content": user},
                ],
            )
            content = response.choices[0].message.content
            return schema.model_validate_json(content)
        except (ValidationError, ValueError) as exc:
            last_error = exc
            continue
        except openai.OpenAIError as exc:
            raise LLMUnavailableError(f"OpenAI request failed: {exc}") from exc

    raise LLMUnavailableError(f"OpenAI response failed validation twice: {last_error}")
