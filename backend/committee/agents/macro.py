"""Macro Analyst Agent — README's third specialist. Focus: sector trends,
market sentiment, broader economic conditions. LLM-backed (Gemini); degrades
to a neutral WAIT when the LLM is unavailable.
"""

from backend.committee.llm.gemini_client import LLMUnavailableError, complete
from backend.committee.market_data.context import MarketContext
from backend.committee.schemas import AgentOutput, Decision, LLMAgentVerdict

AGENT_NAME = "Macro"

SYSTEM_PROMPT = """You are the Macro Analyst on an autonomous investment committee.
Your focus is sector trends, broader market sentiment, and macroeconomic conditions (RBI policy,
budget cycle, global cues) as they bear on one NSE-listed stock's intraday outlook — not
company-specific news or technical price action, which other specialists already cover.
Decide BUY, SELL, or WAIT from a macro/sector lens, with a justified confidence (0.0-1.0)
and evidence describing the macro factors you weighed.
Respond only with the requested JSON shape."""


def analyze(context: MarketContext) -> AgentOutput:
    sector = context.sector or "unknown sector"
    flags = ", ".join(context.context_flags) or "normal"
    market_cap = context.fundamentals.get("marketCap")

    user_prompt = (
        f"Stock: {context.symbol}\n"
        f"Sector: {sector}\n"
        f"Market cap: {market_cap if market_cap else 'unknown'}\n"
        f"Active context flags for this cycle: {flags}\n"
        "Assess the macro/sector backdrop for this stock right now."
    )

    try:
        verdict = complete(SYSTEM_PROMPT, user_prompt, LLMAgentVerdict)
        return verdict.to_agent_output(AGENT_NAME)
    except LLMUnavailableError as exc:
        return AgentOutput(
            agent=AGENT_NAME,
            decision=Decision.WAIT,
            confidence=0.0,
            reasoning=f"LLM unavailable ({exc}) — degraded to neutral instead of failing the cycle.",
            evidence=[f"sector={sector}", f"context_flags={flags}"],
        )
