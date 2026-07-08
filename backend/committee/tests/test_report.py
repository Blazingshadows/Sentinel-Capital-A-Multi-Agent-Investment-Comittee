from datetime import datetime, timezone

from backend.committee.audit.report import cost_breakdown_by_symbol, summarize_pnl
from backend.committee.config import BUYING_POWER
from backend.committee.persistence import models


def _insert_decision(session, stock: str, qty: float, price: float, action_taken: str, total_cost: float) -> None:
    session.add(
        models.Decision(
            cycle_ts=datetime.now(timezone.utc),
            stock=stock,
            agent_recommendations=[],
            debate={},
            influence_breakdown=[],
            consensus_decision=action_taken,
            consensus_confidence=0.5,
            consensus_allocation=0.5,
            consensus_reasoning="test",
            risk_action="APPROVE",
            risk_approved_allocation=0.5,
            risk_volatility_estimate=0.2,
            risk_reason="test",
            action_taken=action_taken,
            qty=qty,
            price=price,
            cost_breakdown={"total_cost": total_cost},
            net_cash_flow=0.0,
        )
    )
    session.commit()


def test_summarize_pnl_with_no_trades(db_session):
    summary = summarize_pnl(db_session, portfolio_value=BUYING_POWER)

    assert summary.trade_count == 0
    assert summary.gross_pnl == 0.0
    assert summary.total_costs == 0.0
    assert summary.net_pnl == 0.0
    assert summary.growth_pct == 0.0


def test_summarize_pnl_computes_gross_as_net_plus_costs(db_session):
    _insert_decision(db_session, "INFY", qty=10, price=1500.0, action_taken="BUY", total_cost=15.0)
    _insert_decision(db_session, "TCS", qty=5, price=3000.0, action_taken="SELL", total_cost=20.0)

    ending_value = BUYING_POWER + 500.0  # e.g. portfolio grew by 500 net of costs
    summary = summarize_pnl(db_session, portfolio_value=ending_value)

    assert summary.trade_count == 2
    assert summary.net_pnl == 500.0
    assert summary.total_costs == 35.0
    assert summary.gross_pnl == 535.0  # net + costs
    assert summary.growth_pct == (500.0 / BUYING_POWER) * 100


def test_cost_breakdown_by_symbol_aggregates_per_stock(db_session):
    _insert_decision(db_session, "INFY", qty=10, price=1500.0, action_taken="BUY", total_cost=15.0)
    _insert_decision(db_session, "INFY", qty=5, price=1510.0, action_taken="SELL", total_cost=8.0)
    _insert_decision(db_session, "TCS", qty=5, price=3000.0, action_taken="SELL", total_cost=20.0)

    breakdown = cost_breakdown_by_symbol(db_session)

    assert breakdown["INFY"] == {"trade_count": 2, "total_costs": 23.0}
    assert breakdown["TCS"] == {"trade_count": 1, "total_costs": 20.0}
