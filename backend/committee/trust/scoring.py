"""Dynamic Trust Framework -- PS #10's mandatory Directional Confidence-Aware
Consensus: agent influence must depend on Confidence, Expertise, Historical
reliability, Trust, Context relevance, and Agreement/disagreement with other
agents, as six independently-tunable factors, not a simple vote average.
Trust itself (historical accuracy) is persisted state owned by
`backend.committee.persistence`; this module is where all six actually get
fused into an influence weight, and where those weights get normalized
across the committee for one cycle.
"""

from sqlalchemy.orm import Session

from backend.committee.config import AGREEMENT_SENSITIVITY, BASE_EXPERTISE, CONTEXT_RELEVANCE_BOOST, TRUST_PRIOR
from backend.committee.persistence.repository import get_trust_score, update_trust_score
from backend.committee.schemas import AgentInfluence, AgentOutput, Decision


def agent_expertise(agent: str) -> float:
    """Static base expertise for this agent at short-horizon intraday calls
    -- "how good this agent generally is," independent of what's happening
    right now (that's context_relevance) or how it's actually performed
    (that's trust)."""
    return BASE_EXPERTISE.get(agent, 1.0)


def context_relevance(agent: str, context_flags: list[str]) -> float:
    """Product of any matching context-day boosts (earnings day, RBI policy
    day, ...) -- "how much this domain matters right now," independent of
    the agent's general expertise."""
    relevance = 1.0
    for flag in context_flags:
        table = CONTEXT_RELEVANCE_BOOST.get(flag)
        if table:
            relevance *= table.get(agent, 1.0)
    return relevance


def agreement_factor(output: AgentOutput, all_outputs: list[AgentOutput], trust_score: float) -> float:
    """This-cycle agreement/disagreement with the rest of the committee.
    WAIT has no direction to agree/disagree about -- neutral factor. For a
    directional call, `redundancy` is the confidence-weighted share of
    *other* directional agents voting the same way (1.0 = everyone agrees,
    0.0 = everyone disagrees).

    Boost-only, deliberately: an agent who diverges from the room while
    carrying above-prior trust is boosted -- informative dissent, the PS's
    named "agreement/disagreement" factor, not just contrarianism for its
    own sake. Full agreement is left neutral (factor 1.0) rather than
    discounted -- because influence gets re-normalized across the committee
    every cycle, a redundancy *discount* applied unevenly (more trusted
    agreeing agents have more "trust edge" to lose than less-trusted ones)
    would perversely end up shrinking the most reliable agreeing voices'
    weight relative to less reliable ones whenever the room genuinely
    agrees -- exactly backwards, and exactly the majority-agreement case
    the committee most needs to stay confident in. An agent with
    below-prior trust gets no boost for disagreeing either (that's the
    unreliable lone-wolf case, not the informative-dissent one)."""
    if output.decision == Decision.WAIT:
        return 1.0

    others = [o for o in all_outputs if o.agent != output.agent and o.decision != Decision.WAIT]
    total_weight = sum(o.confidence for o in others)
    if not others or total_weight <= 0:
        return 1.0

    agree_weight = sum(o.confidence for o in others if o.decision == output.decision)
    redundancy = agree_weight / total_weight  # in [0, 1]

    trust_edge = max(trust_score - TRUST_PRIOR, 0.0) / max(1.0 - TRUST_PRIOR, 1e-9)  # in [0, 1]
    factor = 1.0 + AGREEMENT_SENSITIVITY * (1 - redundancy) * trust_edge
    return min(1 + AGREEMENT_SENSITIVITY, factor)


def build_influences(session: Session, agent_outputs: list[AgentOutput], context_flags: list[str]) -> list[AgentInfluence]:
    """One AgentInfluence per agent output this cycle, with `influence_normalized`
    summing to 1 across the committee — this is what the Consensus
    Orchestrator weights each agent's signed vote by."""
    raw: list[tuple[AgentOutput, float, float, float, float, float]] = []
    for output in agent_outputs:
        trust = get_trust_score(session, output.agent)
        expertise = agent_expertise(output.agent)
        relevance = context_relevance(output.agent, context_flags)
        agreement = agreement_factor(output, agent_outputs, trust)
        influence_raw = output.confidence * trust * expertise * relevance * agreement
        raw.append((output, trust, expertise, relevance, agreement, influence_raw))

    total_raw = sum(item[-1] for item in raw)
    if total_raw <= 0:
        # Every agent reported zero confidence — split influence evenly so
        # normalization still produces a valid (if uninformative) weighting.
        total_raw = len(raw) or 1

    influences = []
    for output, trust, expertise, relevance, agreement, influence_raw in raw:
        normalized = influence_raw / total_raw if total_raw else 1 / len(raw)
        influences.append(
            AgentInfluence(
                agent=output.agent,
                confidence=output.confidence,
                trust_score=trust,
                expertise=expertise,
                context_relevance=relevance,
                agreement_factor=agreement,
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
