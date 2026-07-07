"""Execution Layer — README's final stage: paper trade execution, portfolio
updates, transaction logging. Sizes an order from the Risk Management
Layer's approved allocation and applies real trading costs; never trades
more than what Risk approved."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.committee.config import BUYING_POWER
from backend.committee.execution.cost_model import apply_costs
from backend.committee.schemas import ConsensusDecision, Decision, PortfolioSnapshot, RiskAction, RiskVerdict, TradeRecord


@dataclass
class Portfolio:
    cash: float = BUYING_POWER
    positions: dict[str, float] = field(default_factory=dict)  # symbol -> signed qty

    def mark_to_market(self, prices: dict[str, float]) -> PortfolioSnapshot:
        position_value = sum(qty * prices.get(symbol, 0.0) for symbol, qty in self.positions.items())
        portfolio_value = self.cash + position_value
        return PortfolioSnapshot(
            ts=datetime.now(timezone.utc),
            cash=self.cash,
            positions=dict(self.positions),
            portfolio_value=portfolio_value,
            net_pnl=portfolio_value - BUYING_POWER,
        )


def execute(portfolio: Portfolio, consensus: ConsensusDecision, risk_verdict: RiskVerdict, price: float) -> TradeRecord:
    if (
        consensus.decision == Decision.WAIT
        or risk_verdict.action == RiskAction.REJECT
        or risk_verdict.approved_allocation <= 0
    ):
        return TradeRecord(symbol=consensus.symbol, action=Decision.WAIT, qty=0.0, price=price)

    notional = risk_verdict.approved_allocation * BUYING_POWER
    qty = round(notional / price)
    if qty <= 0:
        return TradeRecord(symbol=consensus.symbol, action=Decision.WAIT, qty=0.0, price=price)

    net_cash_flow, cost_breakdown = apply_costs(consensus.decision, qty, price)

    portfolio.cash += net_cash_flow
    signed_qty = qty if consensus.decision == Decision.BUY else -qty
    portfolio.positions[consensus.symbol] = portfolio.positions.get(consensus.symbol, 0.0) + signed_qty

    return TradeRecord(
        symbol=consensus.symbol,
        action=consensus.decision,
        qty=qty,
        price=price,
        cost_breakdown=cost_breakdown,
        net_cash_flow=net_cash_flow,
    )
