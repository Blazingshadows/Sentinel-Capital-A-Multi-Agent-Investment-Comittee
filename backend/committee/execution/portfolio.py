"""Execution Layer — README's final stage: paper trade execution, portfolio
updates, transaction logging. Sizes an order from the Risk Management
Layer's approved allocation and applies real trading costs; never trades
more than what Risk approved."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.committee.config import BUYING_POWER, CAPITAL
from backend.committee.execution.cost_model import apply_costs
from backend.committee.schemas import ConsensusDecision, Decision, PortfolioSnapshot, RiskAction, RiskVerdict, TradeRecord


@dataclass
class Portfolio:
    cash: float = CAPITAL
    positions: dict[str, float] = field(default_factory=dict)  # symbol -> signed qty

    def mark_to_market(self, prices: dict[str, float]) -> PortfolioSnapshot:
        position_value = sum(qty * prices.get(symbol, 0.0) for symbol, qty in self.positions.items())
        portfolio_value = self.cash + position_value
        return PortfolioSnapshot(
            ts=datetime.now(timezone.utc),
            cash=self.cash,
            positions=dict(self.positions),
            portfolio_value=portfolio_value,
            net_pnl=portfolio_value - CAPITAL,
        )


def execute(portfolio: Portfolio, consensus: ConsensusDecision, risk_verdict: RiskVerdict, price: float) -> TradeRecord:
    """`risk_verdict.approved_allocation` is a *target* position size (as a
    fraction of buying power), not an amount to add on top of whatever's
    already held — trading the full notional every cycle a signal persists
    would let exposure snowball far past the position-limit cap over many
    cycles even though each individual cycle respected it. Only the delta
    between the current position and the target gets traded; a signal that's
    already fully expressed in the current position correctly results in no
    trade at all.
    """
    current_qty = portfolio.positions.get(consensus.symbol, 0.0)

    if consensus.decision == Decision.SWITCH:
        target_qty = 0.0  # fully exit -- the alternative symbol gets its own BUY this same cycle
    elif consensus.decision in (Decision.WAIT, Decision.HOLD) or risk_verdict.action == RiskAction.REJECT or risk_verdict.approved_allocation <= 0:
        target_qty = current_qty  # WAIT/HOLD/REJECT means hold whatever's already there, not liquidate it
    else:
        direction = 1 if consensus.decision == Decision.BUY else -1
        target_notional = direction * risk_verdict.approved_allocation * BUYING_POWER
        target_qty = round(target_notional / price)

    delta_qty = target_qty - current_qty
    if delta_qty == 0:
        return TradeRecord(symbol=consensus.symbol, action=Decision.WAIT, qty=0.0, price=price)

    trade_action = Decision.BUY if delta_qty > 0 else Decision.SELL
    trade_qty = abs(delta_qty)

    net_cash_flow, cost_breakdown = apply_costs(trade_action, trade_qty, price)

    portfolio.cash += net_cash_flow
    portfolio.positions[consensus.symbol] = current_qty + delta_qty

    return TradeRecord(
        symbol=consensus.symbol,
        action=trade_action,
        qty=trade_qty,
        price=price,
        cost_breakdown=cost_breakdown,
        net_cash_flow=net_cash_flow,
    )
