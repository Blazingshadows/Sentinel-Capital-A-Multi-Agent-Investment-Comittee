"""Dispatches each LLM-backed agent to its configured provider
(config.AGENT_PROVIDER_MAP), so different specialist agents genuinely reason
with different models instead of one model role-playing three personas.
Callers (news_sentiment.py, macro.py, contrarian.py) import only this
module, never a specific provider client directly.
"""

from typing import TypeVar

from pydantic import BaseModel

from backend.committee.config import AGENT_PROVIDER_MAP
from backend.committee.llm import anthropic_client, gemini_client, openai_client

T = TypeVar("T", bound=BaseModel)

_PROVIDERS = {
    "gemini": gemini_client,
    "openai": openai_client,
    "anthropic": anthropic_client,
}

_PROVIDER_ERRORS = (
    gemini_client.LLMUnavailableError,
    openai_client.LLMUnavailableError,
    anthropic_client.LLMUnavailableError,
)


class LLMUnavailableError(RuntimeError):
    """Unified across providers so agents only need to catch one exception type."""


def complete_for_agent(agent_name: str, system: str, user: str, schema: type[T]) -> T:
    provider_name = AGENT_PROVIDER_MAP.get(agent_name, "gemini")
    provider = _PROVIDERS[provider_name]
    try:
        return provider.complete(system, user, schema)
    except _PROVIDER_ERRORS as exc:
        raise LLMUnavailableError(f"{provider_name} unavailable for {agent_name}: {exc}") from exc
