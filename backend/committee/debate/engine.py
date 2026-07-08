"""Debate Layer — README's 4-step flow: independent recommendations (already
computed by the specialist agents) -> agents review opposing opinions ->
Contrarian challenges assumptions -> agents may revise confidence scores.

The revision pass is a single deterministic rule rather than N further LLM
calls: an agent whose call the Contrarian directly disagrees with gets its
confidence damped in proportion to the Contrarian's own confidence: a
low-confidence dissent barely moves it, a highly-confident one roughly
halves it. Agents the Contrarian agrees with (or has no opinion on, i.e. its
own vote is WAIT) are left untouched — corroboration isn't grounds to walk
back a call.
"""

from backend.committee.config import REVISION_DAMPING_FACTOR
from backend.committee.debate.contrarian import analyze as contrarian_analyze
from backend.committee.market_data.context import MarketContext
from backend.committee.schemas import AgentOutput, DebateResult, Decision


def _revise(agent_output: AgentOutput, contrarian_output: AgentOutput) -> AgentOutput:
    disagreement = (
        agent_output.decision != Decision.WAIT
        and contrarian_output.decision != Decision.WAIT
        and agent_output.decision != contrarian_output.decision
    )
    if not disagreement:
        return agent_output

    damping = contrarian_output.confidence * REVISION_DAMPING_FACTOR
    revised_confidence = round(max(0.0, agent_output.confidence * (1 - damping)), 4)
    return agent_output.model_copy(
        update={
            "confidence": revised_confidence,
            "reasoning": (
                f"{agent_output.reasoning} "
                f"[confidence revised {agent_output.confidence:.2f} -> {revised_confidence:.2f} "
                f"after Contrarian challenge: {contrarian_output.reasoning}]"
            ),
        }
    )


def run_debate(context: MarketContext, original_recommendations: list[AgentOutput]) -> DebateResult:
    contrarian_verdict = contrarian_analyze(context, original_recommendations)
    contrarian_output = contrarian_verdict.to_agent_output()

    revised = [_revise(output, contrarian_output) for output in original_recommendations]
    revised.append(contrarian_output)

    return DebateResult(
        original_recommendations=original_recommendations,
        contrarian_challenge=contrarian_verdict.challenge,
        contrarian_risk_observations=contrarian_verdict.risk_observations,
        revised_recommendations=revised,
    )
