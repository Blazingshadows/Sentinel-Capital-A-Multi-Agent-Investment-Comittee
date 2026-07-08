from backend.committee.consensus.orchestrator import run_consensus
from backend.committee.schemas import AgentOutput, DebateResult, Decision


def test_worked_example_matches_hand_computed_dcs(db_session):
    """Technical=BUY(0.8), News&Sentiment=BUY(0.6), Macro=SELL(0.3), Contrarian=WAIT(0.5),
    cold-start trust (0.5) and 'normal' context flags -> hand-computed DCS = +0.503."""
    outputs = [
        AgentOutput(agent="Technical", decision=Decision.BUY, confidence=0.8, reasoning="x", evidence=[]),
        AgentOutput(agent="News & Sentiment", decision=Decision.BUY, confidence=0.6, reasoning="x", evidence=[]),
        AgentOutput(agent="Macro", decision=Decision.SELL, confidence=0.3, reasoning="x", evidence=[]),
        AgentOutput(agent="Contrarian", decision=Decision.WAIT, confidence=0.5, reasoning="x", evidence=[]),
    ]
    debate = DebateResult(original_recommendations=outputs, contrarian_challenge="none", revised_recommendations=outputs)

    result = run_consensus(db_session, "INFY", debate, ["normal"])

    assert result.decision == Decision.BUY
    assert abs(result.confidence - 0.5029) < 0.001
    assert abs(result.allocation - 1.0057) < 0.001


def test_low_signal_yields_wait(db_session):
    outputs = [
        AgentOutput(agent="Technical", decision=Decision.BUY, confidence=0.1, reasoning="x", evidence=[]),
        AgentOutput(agent="News & Sentiment", decision=Decision.SELL, confidence=0.1, reasoning="x", evidence=[]),
        AgentOutput(agent="Macro", decision=Decision.WAIT, confidence=0.0, reasoning="x", evidence=[]),
        AgentOutput(agent="Contrarian", decision=Decision.WAIT, confidence=0.0, reasoning="x", evidence=[]),
    ]
    debate = DebateResult(original_recommendations=outputs, contrarian_challenge="none", revised_recommendations=outputs)

    result = run_consensus(db_session, "INFY", debate, ["normal"])

    assert result.decision == Decision.WAIT
    assert result.allocation == 0.0
