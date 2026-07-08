from backend.committee.persistence.repository import get_trust_score, update_trust_score
from backend.committee.schemas import AgentOutput, Decision
from backend.committee.trust.scoring import build_influences, context_relevance


def test_context_relevance_boosts_matching_agent():
    normal = context_relevance("News & Sentiment", ["normal"])
    boosted = context_relevance("News & Sentiment", ["earnings_day"])
    assert boosted > normal


def test_influences_normalize_to_one(db_session):
    outputs = [
        AgentOutput(agent="Technical", decision=Decision.BUY, confidence=0.8, reasoning="x", evidence=[]),
        AgentOutput(agent="Macro", decision=Decision.SELL, confidence=0.3, reasoning="x", evidence=[]),
    ]
    influences = build_influences(db_session, outputs, ["normal"])
    assert abs(sum(inf.influence_normalized for inf in influences) - 1.0) < 1e-9


def test_trust_score_updates_from_resolved_predictions(db_session):
    assert get_trust_score(db_session, "Technical") == 0.5

    from datetime import datetime, timezone

    from backend.committee.persistence import models

    for correct in [1, 1, 1, 0]:
        db_session.add(
            models.AgentPrediction(
                cycle_ts=datetime.now(timezone.utc), stock="INFY", agent="Technical",
                direction=1, confidence=0.8, outcome_direction=1 if correct else -1, correct=correct,
            )
        )
    db_session.commit()

    updated = update_trust_score(db_session, "Technical")
    assert updated > 0.5  # 3/4 correct pulls trust above the 0.5 cold-start prior
    assert get_trust_score(db_session, "Technical") == updated
