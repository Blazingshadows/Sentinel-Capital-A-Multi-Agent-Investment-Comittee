"""Consensus Orchestrator — README's synthesis stage. Pure Python math, no
LLM call: fuses the Debate Layer's revised recommendations into one
allocation recommendation via the Dynamic Trust Framework's
`Agent Influence = Confidence x Trust x Expertise x Context Relevance x
Agreement`.
"""

from sqlalchemy.orm import Session

from backend.committee.config import DECISION_THRESHOLD_WAIT, LEVERAGE
from backend.committee.schemas import ConsensusDecision, DebateResult, Decision
from backend.committee.trust.scoring import build_influences


def run_consensus(
    session: Session, symbol: str, debate: DebateResult, context_flags: list[str], current_position: float = 0.0
) -> ConsensusDecision:
    influences = build_influences(session, debate.revised_recommendations, context_flags)

    # Directional Confidence Score: weighted sum of signed votes, in [-1, 1].
    dcs = sum(inf.influence_normalized * inf.signed_vote for inf in influences)
    confidence = abs(dcs)

    if confidence < DECISION_THRESHOLD_WAIT:
        # No clear edge either way. PS distinguishes WAIT (nothing held, no
        # reason to act) from HOLD (a position already exists and the
        # committee's lack of a new edge is itself a decision to maintain
        # it, not silence) -- individual specialists never see portfolio
        # state, so this distinction can only be made here.
        decision = Decision.HOLD if current_position != 0 else Decision.WAIT
        allocation = 0.0
    else:
        decision = Decision.BUY if dcs > 0 else Decision.SELL
        # Full committee confidence (1.0) maps to full leverage utilization
        # (LEVERAGE x base capital) — the Risk layer applies its own caps
        # and volatility trims on top of this before anything gets executed.
        allocation = min(confidence * LEVERAGE, float(LEVERAGE))

    reasoning = _build_reasoning(dcs, decision, influences, debate)

    return ConsensusDecision(
        symbol=symbol,
        decision=decision,
        confidence=round(confidence, 4),
        allocation=round(allocation, 4),
        reasoning=reasoning,
        influence_breakdown=influences,
        debate=debate,
    )


def _build_reasoning(dcs: float, decision: Decision, influences, debate: DebateResult) -> str:
    ranked = sorted(influences, key=lambda inf: inf.influence_normalized, reverse=True)
    votes = "; ".join(
        f"{inf.agent} (weight={inf.influence_normalized:.2f}, vote={inf.signed_vote:+.2f}, "
        f"trust={inf.trust_score:.2f}, expertise={inf.expertise:.2f}, "
        f"context={inf.context_relevance:.2f}, agreement={inf.agreement_factor:.2f})"
        for inf in ranked
    )
    return (
        f"Directional Confidence Score={dcs:+.2f} -> {decision.value}. "
        f"Not a simple vote average: each agent's weight is its own confidence multiplied by four "
        f"independently-tracked factors -- historical trust, domain expertise, today's context "
        f"relevance, and this-cycle agreement/disagreement with the rest of the committee -- so two "
        f"agents at the same confidence can carry very different influence. "
        f"Weighted committee votes: {votes}. "
        f"Contrarian challenge considered: {debate.contrarian_challenge}"
    )
