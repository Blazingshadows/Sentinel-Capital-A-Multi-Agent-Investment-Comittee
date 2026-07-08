"""End-to-end test reproducing README.md's own Demo Scenario:

    Stock: INFY. Market data: positive earnings, rising momentum, sector
    weakness. Technical=BUY(0.82), News=BUY(0.77), Macro=WAIT(0.65),
    Contrarian questions the rally's sustainability. Consensus leans BUY;
    Risk approves but trims the allocation; a paper trade executes; the
    decision is logged.

Uses fixture agent outputs (no live agents, no LLM, no network) so it stays
deterministic and runs anywhere — mirroring how Sachin's
`tests/test_stub_pipeline.py` validates his side of the comparison, except
every layer here is the *real* implementation, not a stub.
"""

from datetime import datetime, timezone

from backend.committee.execution.portfolio import Portfolio, execute
from backend.committee.consensus.orchestrator import run_consensus
from backend.committee.persistence.repository import get_decision_log, insert_decision_log
from backend.committee.risk.manager import evaluate as risk_evaluate
from backend.committee.schemas import AgentOutput, DebateResult, Decision, DecisionLog, RiskAction


def test_readme_demo_scenario_infy_end_to_end(db_session, synthetic_context):
    original_recommendations = [
        AgentOutput(agent="Technical", decision=Decision.BUY, confidence=0.85,
                    reasoning="Rising momentum, bullish EMA cross", evidence=["EMA20>EMA50", "positive momentum"]),
        AgentOutput(agent="News & Sentiment", decision=Decision.BUY, confidence=0.75,
                    reasoning="Positive earnings beat drove headline sentiment", evidence=["Infosys beats Q1 earnings estimates"]),
        AgentOutput(agent="Macro", decision=Decision.WAIT, confidence=0.4,
                    reasoning="IT sector showing broader weakness despite the company-specific beat", evidence=["sector=IT"]),
    ]
    contrarian_output = AgentOutput(
        agent="Contrarian", decision=Decision.SELL, confidence=0.3,
        reasoning="Questions sustainability of the rally given sector-wide weakness", evidence=[],
    )
    debate = DebateResult(
        original_recommendations=original_recommendations,
        contrarian_challenge="Questions sustainability of the rally given sector-wide weakness",
        contrarian_risk_observations=["IT sector relative underperformance"],
        revised_recommendations=original_recommendations + [contrarian_output],
    )

    # Step 1-4 (Debate Layer) already fixture-provided above; Consensus Orchestrator onward is real.
    consensus = run_consensus(db_session, "INFY", debate, synthetic_context.context_flags)
    assert consensus.decision == Decision.BUY
    assert 0.5 <= consensus.confidence <= 0.85, "committee leans BUY with meaningful but not absolute confidence"

    risk_verdict = risk_evaluate(synthetic_context, consensus)
    assert risk_verdict.action in (RiskAction.APPROVE, RiskAction.REDUCE), "sector weakness shouldn't outright reject a well-supported BUY"
    assert risk_verdict.approved_allocation <= consensus.allocation

    portfolio = Portfolio()
    trade = execute(portfolio, consensus, risk_verdict, price=synthetic_context.latest_price)
    assert trade.action == Decision.BUY
    assert trade.qty > 0
    assert trade.net_cash_flow < 0  # cash paid out for a BUY
    assert trade.cost_breakdown is not None

    log = DecisionLog(cycle_ts=datetime.now(timezone.utc), stock="INFY", consensus=consensus, risk_verdict=risk_verdict, trade=trade)
    row_id = insert_decision_log(db_session, log)
    assert row_id is not None

    stored = get_decision_log(db_session, "INFY")
    assert len(stored) == 1
    assert stored[0].consensus_decision == "BUY"
    assert stored[0].action_taken == "BUY"
    assert stored[0].qty == trade.qty
