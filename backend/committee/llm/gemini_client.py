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

MODEL_NAME = "gemini-2.5-flash"

T = TypeVar("T", bound=BaseModel)

_configured = False

_UNSUPPORTED_SCHEMA_KEYS = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "title"}


class LLMUnavailableError(RuntimeError):
    """No API key configured, or every attempt returned an unusable response."""


def _ensure_configured() -> None:
    global _configured
    if not settings.gemini_api_key:
        raise LLMUnavailableError("GEMINI_API_KEY is not set")
    if not _configured:
        genai.configure(api_key=settings.gemini_api_key)
        _configured = True


def _strip_unsupported_schema_keys(value):
    if isinstance(value, dict):
        return {
            key: _strip_unsupported_schema_keys(child)
            for key, child in value.items()
            if key not in _UNSUPPORTED_SCHEMA_KEYS
        }
    if isinstance(value, list):
        return [_strip_unsupported_schema_keys(item) for item in value]
    return value


def _inline_refs(node, defs: dict):
    """Gemini's response_schema rejects `$ref`/`$defs` outright ("Unknown
    field for Schema: $defs") -- Pydantic v2 emits both for any Enum field
    (e.g. LLMAgentVerdict.decision), so those have to be resolved inline
    before the schema is usable here."""
    if isinstance(node, dict):
        if "$ref" in node:
            ref_name = node["$ref"].rsplit("/", 1)[-1]
            return _inline_refs(defs[ref_name], defs)
        if "allOf" in node and len(node["allOf"]) == 1:
            resolved = _inline_refs(node["allOf"][0], defs)
            merged = {**resolved, **{k: v for k, v in node.items() if k != "allOf"}}
            return _inline_refs(merged, defs)
        return {key: _inline_refs(child, defs) for key, child in node.items() if key != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]
    return node


def _prepare_schema(schema_dict: dict) -> dict:
    inlined = _inline_refs(schema_dict, schema_dict.get("$defs", {}))
    return _strip_unsupported_schema_keys(inlined)


def complete(system: str, user: str, schema: type[T]) -> T:
    _ensure_configured()
    model = genai.GenerativeModel(MODEL_NAME, system_instruction=system)
    generation_config = genai.GenerationConfig(
        response_mime_type="application/json",
        response_schema=_prepare_schema(schema.model_json_schema()),
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
