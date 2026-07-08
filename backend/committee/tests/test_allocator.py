from backend.committee.config import BUYING_POWER
from backend.committee.execution.portfolio import Portfolio
from backend.committee.orchestration.allocator import AllocationCandidate, allocate_capital
from backend.committee.schemas import AgentOutput, ConsensusDecision, DebateResult, Decision, RiskAction, RiskVerdict


def _candidate(symbol: str, price: float, confidence: float, allocation: float) -> AllocationCandidate:
    agent = AgentOutput(agent="Technical", decision=Decision.BUY, confidence=confidence, reasoning="x", evidence=[])
    debate = DebateResult(original_recommendations=[agent], contrarian_challenge="none", revised_recommendations=[agent])
    consensus = ConsensusDecision(
        symbol=symbol, decision=Decision.BUY, confidence=confidence, allocation=allocation,
        reasoning="test", influence_breakdown=[], debate=debate,
    )
    risk_verdict = RiskVerdict(action=RiskAction.APPROVE, approved_allocation=allocation, volatility_estimate=0.2, reason="approved")
    return AllocationCandidate(symbol=symbol, price=price, consensus=consensus, risk_verdict=risk_verdict)


def test_three_simultaneous_max_buys_no_longer_exceed_buying_power():
    """Regression test for the exact scenario that surfaced the bug: three
    symbols each independently approved at the 100% position cap must not
    jointly request 291% of buying power -- confirmed by hand before this
    fix existed."""
    portfolio = Portfolio()
    candidates = [
        _candidate("RELIANCE", price=1300.0, confidence=0.9, allocation=1.0),
        _candidate("TCS", price=3200.0, confidence=0.9, allocation=1.0),
        _candidate("INFY", price=1500.0, confidence=0.9, allocation=1.0),
    ]

    adjusted = allocate_capital(candidates, portfolio)

    total_requested_notional = sum(v.approved_allocation * BUYING_POWER for v in adjusted.values())
    assert total_requested_notional <= BUYING_POWER + 1e-6


def test_equal_confidence_candidates_split_headroom_equally():
    portfolio = Portfolio()
    candidates = [
        _candidate("A", price=1000.0, confidence=0.8, allocation=1.0),
        _candidate("B", price=1000.0, confidence=0.8, allocation=1.0),
    ]

    adjusted = allocate_capital(candidates, portfolio)

    assert adjusted["A"].approved_allocation == adjusted["B"].approved_allocation
    assert abs(adjusted["A"].approved_allocation - 0.5) < 1e-6


def test_higher_confidence_gets_larger_share():
    portfolio = Portfolio()
    candidates = [
        _candidate("A", price=1000.0, confidence=0.9, allocation=1.0),
        _candidate("B", price=1000.0, confidence=0.3, allocation=1.0),
    ]

    adjusted = allocate_capital(candidates, portfolio)

    assert adjusted["A"].approved_allocation > adjusted["B"].approved_allocation
    # 0.9 / (0.9+0.3) = 0.75 share of 1.0x total headroom
    assert abs(adjusted["A"].approved_allocation - 0.75) < 1e-6


def test_sufficient_headroom_leaves_allocations_unchanged():
    portfolio = Portfolio()
    candidates = [_candidate("A", price=1000.0, confidence=0.9, allocation=0.3)]

    adjusted = allocate_capital(candidates, portfolio)

    assert adjusted["A"].approved_allocation == 0.3
    assert adjusted["A"].action == RiskAction.APPROVE


def test_reducing_an_existing_position_is_never_throttled():
    portfolio = Portfolio()
    portfolio.positions["A"] = 15.0  # already long ~100% of buying power at price 1000 with leverage headroom used
    portfolio.cash = 5000.0

    agent = AgentOutput(agent="Technical", decision=Decision.SELL, confidence=0.9, reasoning="x", evidence=[])
    debate = DebateResult(original_recommendations=[agent], contrarian_challenge="none", revised_recommendations=[agent])
    reduce_consensus = ConsensusDecision(
        symbol="A", decision=Decision.SELL, confidence=0.9, allocation=0.1,
        reasoning="reduce", influence_breakdown=[], debate=debate,
    )
    reduce_verdict = RiskVerdict(action=RiskAction.APPROVE, approved_allocation=0.1, volatility_estimate=0.2, reason="reduce")
    candidates = [AllocationCandidate(symbol="A", price=1000.0, consensus=reduce_consensus, risk_verdict=reduce_verdict)]

    adjusted = allocate_capital(candidates, portfolio)

    assert adjusted["A"].approved_allocation == 0.1
    assert adjusted["A"].action == RiskAction.APPROVE
