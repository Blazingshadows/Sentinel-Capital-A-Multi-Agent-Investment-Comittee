"""Contrarian Agent — README's fourth specialist and the Debate Layer's
challenger. Reviews the other agents' independent recommendations, attacks
weak arguments, surfaces alternative interpretations, and casts its own
directional vote in the same call. Routed to its own LLM provider (see
config.AGENT_PROVIDER_MAP) deliberately — a different lab's model is more
likely to genuinely disagree than the same model prompted to play devil's
advocate.
"""

from backend.committee.llm.router import LLMUnavailableError, complete_for_agent
from backend.committee.market_data.context import MarketContext
from backend.committee.schemas import AgentOutput, ContrarianVerdict, Decision

AGENT_NAME = "Contrarian"

SYSTEM_PROMPT = """You are the Contrarian on an autonomous INTRADAY investment committee. Your job is to
challenge the other specialists' independent recommendations for one NSE-listed stock: identify blind
spots, attack weak arguments, and surface alternative interpretations they may have missed. Then cast your
own BUY/SELL/WAIT vote with a justified confidence (0.0-1.0).

Being the skeptic does not mean defaulting to WAIT. If your challenge reveals the leading proposal is wrong
or overconfident, say which direction you actually believe is correct and vote it — a sharp contrarian call
is itself directional, not just "everyone else is uncertain so let's do nothing." Only vote WAIT when you
genuinely have no directional view after the challenge, not merely because you found flaws in someone
else's reasoning.

Confidence must measure the strength of YOUR directional conviction, not how prudent your call feels. A
WAIT vote means "I have no edge here" and should itself carry LOW confidence (roughly 0.0-0.2) — this
committee's consensus math treats a high-confidence WAIT as a heavily-weighted claim that can silently
cancel out other specialists' genuine directional signals, so do not use it as a safe default.

Write `challenge` as a short paragraph directly addressing the leading proposal (the recommendation with
the highest confidence among the others), and list concrete `risk_observations`.
Respond only with the requested JSON shape."""


def _format_recommendations(recommendations: list[AgentOutput]) -> str:
    return "\n".join(
        f"- {rec.agent}: {rec.decision.value} (confidence={rec.confidence:.2f}) — {rec.reasoning}"
        for rec in recommendations
    )


def analyze(context: MarketContext, original_recommendations: list[AgentOutput]) -> ContrarianVerdict:
    user_prompt = (
        f"Stock: {context.symbol}\n"
        f"Independent committee recommendations this cycle:\n"
        f"{_format_recommendations(original_recommendations)}\n\n"
        "Challenge the leading proposal and cast your own vote."
    )

    try:
        return complete_for_agent(AGENT_NAME, SYSTEM_PROMPT, user_prompt, ContrarianVerdict)
    except LLMUnavailableError as exc:
        return ContrarianVerdict(
            decision=Decision.WAIT,
            confidence=0.0,
            reasoning=f"LLM unavailable ({exc}) — degraded to neutral instead of failing the cycle.",
            evidence=[],
            challenge="No contrarian challenge available this cycle (LLM unavailable).",
            risk_observations=[],
        )
