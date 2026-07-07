"""Dynamic Trust Framework — README §"Dynamic Trust Framework":
`Agent Influence = Confidence x Trust Score x Context Relevance`.
Trust itself (historical accuracy) is persisted state owned by
`backend.committee.persistence`; this module is where trust, context
relevance, and confidence actually get fused into an influence weight, and
where those weights get normalized across the committee for one cycle.
"""

from sqlalchemy.orm import Session

from backend.committee.config import BASE_EXPERTISE, CONTEXT_RELEVANCE_BOOST
from backend.committee.persistence.repository import get_trust_score, update_trust_score
from backend.committee.schemas import AgentInfluence, AgentOutput


def context_relevance(agent: str, context_flags: list[str]) -> float:
    """Static base expertise for this agent x the product of any matching
    context-day boosts (earnings day, RBI policy day, ...). Kept as its own
    factor so "how good this agent generally is" and "how much this domain
    matters right now" stay independently tunable, per README."""
    relevance = BASE_EXPERTISE.get(agent, 1.0)
    for flag in context_flags:
        table = CONTEXT_RELEVANCE_BOOST.get(flag)
        if table:
            relevance *= table.get(agent, 1.0)
    return relevance


def build_influences(session: Session, agent_outputs: list[AgentOutput], context_flags: list[str]) -> list[AgentInfluence]:
    """One AgentInfluence per agent output this cycle, with `influence_normalized`
    summing to 1 across the committee — this is what the Consensus
    Orchestrator weights each agent's signed vote by."""
    raw: list[tuple[AgentOutput, float, float, float]] = []
    for output in agent_outputs:
        trust = get_trust_score(session, output.agent)
        relevance = context_relevance(output.agent, context_flags)
        influence_raw = output.confidence * trust * relevance
        raw.append((output, trust, relevance, influence_raw))

    total_raw = sum(item[3] for item in raw)
    if total_raw <= 0:
        # Every agent reported zero confidence — split influence evenly so
        # normalization still produces a valid (if uninformative) weighting.
        total_raw = len(raw) or 1

    influences = []
    for output, trust, relevance, influence_raw in raw:
        normalized = influence_raw / total_raw if total_raw else 1 / len(raw)
        influences.append(
            AgentInfluence(
                agent=output.agent,
                confidence=output.confidence,
                trust_score=trust,
                context_relevance=relevance,
                influence_raw=influence_raw,
                influence_normalized=normalized,
                signed_vote=output.signed_vote,
            )
        )
    return influences


def refresh_trust_scores(session: Session, agents: list[str]) -> dict[str, float]:
    """Called once per cycle (after the previous cycle's outcomes have been
    backfilled) so the Consensus Orchestrator always weights against
    up-to-date historical accuracy."""
    return {agent: update_trust_score(session, agent) for agent in agents}
