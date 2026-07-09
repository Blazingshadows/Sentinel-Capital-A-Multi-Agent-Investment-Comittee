"""Macro Analyst Agent — README's third specialist. Focus: sector trends,
market sentiment, broader economic conditions. LLM-backed, routed through
config.AGENT_PROVIDER_MAP; degrades to a neutral WAIT when the LLM is
unavailable.
"""

from backend.committee.llm.router import LLMUnavailableError, complete_for_agent
from backend.committee.market_data.context import MarketContext
from backend.committee.schemas import AgentOutput, Decision, LLMAgentVerdict

AGENT_NAME = "Macro"

SYSTEM_PROMPT = """You are the Macro Analyst on an autonomous INTRADAY investment committee trading NSE
large-caps. Your focus is sector trends, broader market sentiment, and macroeconomic conditions (RBI policy,
budget cycle, global cues) as they bear on one NSE-listed stock's intraday outlook — not company-specific
news or technical price action, which other specialists already cover.

This is a same-day trading desk, not a swing desk: overnight macro uncertainty (a pending RBI decision,
unresolved global cues, unclear FPI flows) is the normal operating condition, not a reason to abstain — by
the time it resolves, the trading window is closed. Decide BUY, SELL, or WAIT from a macro/sector lens.
Weigh whichever side of the macro picture currently has more support and take that side, sized to how
strong the edge is; do not round a mild lean down to WAIT just because the picture isn't unanimous. Reserve
WAIT for cycles where the macro backdrop is genuinely balanced or irrelevant to this stock, not merely
uncertain.

Confidence must measure the strength of your directional conviction, not how prudent your call feels: a
mild lean is a real, tradeable edge and should be reported as such (e.g. 0.3-0.5), while a WAIT call — "no
usable macro edge either way" — should itself carry LOW confidence (roughly 0.0-0.2). A high-confidence
WAIT is a strong claim that you're certain there's no edge, and in this committee's consensus math it can
silently override other specialists' directional votes — reserve it for a genuine coin flip, not as a
hedge.

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
        verdict = complete_for_agent(AGENT_NAME, SYSTEM_PROMPT, user_prompt, LLMAgentVerdict)
        return verdict.to_agent_output(AGENT_NAME)
    except LLMUnavailableError as exc:
        return AgentOutput(
            agent=AGENT_NAME,
            decision=Decision.WAIT,
            confidence=0.0,
            reasoning=f"LLM unavailable ({exc}) — degraded to neutral instead of failing the cycle.",
            evidence=[f"sector={sector}", f"context_flags={flags}"],
        )
