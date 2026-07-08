from backend.committee.config import MAX_POSITION_ALLOCATION
from backend.committee.risk import manager
from backend.committee.schemas import AgentOutput, ConsensusDecision, DebateResult, Decision, RiskAction


def _consensus(decision: Decision, confidence: float, allocation: float) -> ConsensusDecision:
    agent = AgentOutput(agent="Technical", decision=decision, confidence=confidence, reasoning="x", evidence=[])
    debate = DebateResult(original_recommendations=[agent], contrarian_challenge="none", revised_recommendations=[agent])
    return ConsensusDecision(
        symbol="INFY", decision=decision, confidence=confidence, allocation=allocation,
        reasoning="test", influence_breakdown=[], debate=debate,
    )


def test_wait_consensus_is_approved_with_zero_allocation(synthetic_context, monkeypatch):
    monkeypatch.setattr(manager, "estimate_annualized_volatility", lambda closes: 0.2)
    verdict = manager.evaluate(synthetic_context, _consensus(Decision.WAIT, 0.0, 0.0))
    assert verdict.action == RiskAction.APPROVE
    assert verdict.approved_allocation == 0.0


def test_low_volatility_within_cap_is_approved_as_proposed(synthetic_context, monkeypatch):
    monkeypatch.setattr(manager, "estimate_annualized_volatility", lambda closes: 0.2)
    verdict = manager.evaluate(synthetic_context, _consensus(Decision.BUY, 0.6, 0.6))
    assert verdict.action == RiskAction.APPROVE
    assert verdict.approved_allocation == 0.6


def test_oversized_allocation_is_reduced_to_cap(synthetic_context, monkeypatch):
    monkeypatch.setattr(manager, "estimate_annualized_volatility", lambda closes: 0.2)
    verdict = manager.evaluate(synthetic_context, _consensus(Decision.BUY, 0.9, 1.8))
    assert verdict.action == RiskAction.REDUCE
    assert verdict.approved_allocation == MAX_POSITION_ALLOCATION


def test_high_volatility_trims_allocation(synthetic_context, monkeypatch):
    monkeypatch.setattr(manager, "estimate_annualized_volatility", lambda closes: 0.6)
    verdict = manager.evaluate(synthetic_context, _consensus(Decision.BUY, 0.5, 0.5))
    assert verdict.action == RiskAction.REDUCE
    assert verdict.approved_allocation < 0.5


def test_extreme_volatility_is_rejected(synthetic_context, monkeypatch):
    monkeypatch.setattr(manager, "estimate_annualized_volatility", lambda closes: 1.5)
    verdict = manager.evaluate(synthetic_context, _consensus(Decision.BUY, 0.9, 1.5))
    assert verdict.action == RiskAction.REJECT
    assert verdict.approved_allocation == 0.0
