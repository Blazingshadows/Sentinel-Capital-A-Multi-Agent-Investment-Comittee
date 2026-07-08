from backend.committee.config import BUYING_POWER
from backend.committee.execution.portfolio import Portfolio, execute
from backend.committee.schemas import AgentOutput, ConsensusDecision, DebateResult, Decision, RiskAction, RiskVerdict


def _consensus(decision: Decision, allocation: float) -> ConsensusDecision:
    agent = AgentOutput(agent="Technical", decision=decision, confidence=0.8, reasoning="x", evidence=[])
    debate = DebateResult(original_recommendations=[agent], contrarian_challenge="none", revised_recommendations=[agent])
    return ConsensusDecision(
        symbol="INFY", decision=decision, confidence=0.8, allocation=allocation,
        reasoning="test", influence_breakdown=[], debate=debate,
    )


def _approve(allocation: float) -> RiskVerdict:
    return RiskVerdict(action=RiskAction.APPROVE, approved_allocation=allocation, volatility_estimate=0.2, reason="test")


def test_repeated_same_direction_signal_does_not_snowball():
    """Regression test: a persistent BUY signal across many cycles must not
    keep adding to the position past the approved allocation -- surfaced by
    a real committee-vs-baseline comparison run that produced a >100% max
    drawdown from unbounded position accumulation."""
    portfolio = Portfolio()
    consensus = _consensus(Decision.BUY, allocation=0.5)
    risk_verdict = _approve(0.5)

    first_trade = execute(portfolio, consensus, risk_verdict, price=1000.0)
    assert first_trade.action == Decision.BUY
    assert first_trade.qty > 0

    for _ in range(10):
        trade = execute(portfolio, consensus, risk_verdict, price=1000.0)
        assert trade.action == Decision.WAIT
        assert trade.qty == 0.0

    expected_qty = round(0.5 * BUYING_POWER / 1000.0)
    assert portfolio.positions["INFY"] == expected_qty


def test_signal_flip_trades_the_full_delta():
    portfolio = Portfolio()
    execute(portfolio, _consensus(Decision.BUY, 0.5), _approve(0.5), price=1000.0)
    long_qty = portfolio.positions["INFY"]
    assert long_qty > 0

    flip_trade = execute(portfolio, _consensus(Decision.SELL, 0.3), _approve(0.3), price=1000.0)

    expected_short_qty = -round(0.3 * BUYING_POWER / 1000.0)
    assert portfolio.positions["INFY"] == expected_short_qty
    assert flip_trade.action == Decision.SELL
    assert flip_trade.qty == long_qty - expected_short_qty


def test_wait_holds_existing_position_rather_than_liquidating():
    portfolio = Portfolio()
    execute(portfolio, _consensus(Decision.BUY, 0.5), _approve(0.5), price=1000.0)
    held_qty = portfolio.positions["INFY"]

    wait_consensus = _consensus(Decision.WAIT, 0.0)
    wait_verdict = RiskVerdict(action=RiskAction.APPROVE, approved_allocation=0.0, volatility_estimate=0.2, reason="wait")
    trade = execute(portfolio, wait_consensus, wait_verdict, price=1000.0)

    assert trade.action == Decision.WAIT
    assert trade.qty == 0.0
    assert portfolio.positions["INFY"] == held_qty
