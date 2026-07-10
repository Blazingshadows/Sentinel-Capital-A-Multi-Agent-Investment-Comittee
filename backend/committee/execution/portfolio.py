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
    entry_prices: dict[str, float] = field(default_factory=dict)  # symbol -> cost basis of the current position
    # In-memory only, not persisted/restored across a process restart (the
    # Dynamic Trust Framework's other position state, portfolio_snapshots,
    # only stores cash/positions/value) -- a stop-loss simply won't fire for
    # a position carried across a restart until it's re-opened. Acceptable
    # for a single-session demo; would need its own persisted column to
    # survive restarts.

    def reset(self) -> None:
        """Back to flat/full-cash in place (not a new instance -- callers
        like `app.state.portfolio` hold a reference to this exact object).
        Every Replay Mode run rebuilds its `ReplayFeed`s from the start of
        the cached window (see replay/player.py), so a position/cost-basis
        left over from a previous replay run would get marked against
        whatever price that same starting bar has -- a different point in
        simulated time than where the position was actually opened. Call
        this before a fresh replay run starts so its price feed and its
        portfolio state always describe the same simulated timeline."""
        self.cash = CAPITAL
        self.positions.clear()
        self.entry_prices.clear()

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


def _update_entry_price(portfolio: Portfolio, symbol: str, current_qty: float, new_qty: float, delta_qty: float, price: float) -> None:
    """Cost basis for the stop-loss check. Closed to flat -> no position to
    track. Opened fresh or flipped direction (long to short or back) -> cost
    basis is just this fill's price, since there's no prior same-direction
    position to average against. Added to an existing same-direction
    position -> quantity-weighted average of old and new cost. Reduced
    (without flattening or flipping) -> cost basis of the remaining shares
    is unchanged, nothing to do."""
    if new_qty == 0:
        portfolio.entry_prices.pop(symbol, None)
    elif current_qty == 0 or (current_qty > 0) != (new_qty > 0):
        portfolio.entry_prices[symbol] = price
    elif abs(new_qty) > abs(current_qty):
        old_price = portfolio.entry_prices.get(symbol, price)
        portfolio.entry_prices[symbol] = (abs(current_qty) * old_price + abs(delta_qty) * price) / abs(new_qty)


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
    elif consensus.decision in (Decision.WAIT, Decision.HOLD) or risk_verdict.action == RiskAction.REJECT:
        target_qty = current_qty  # WAIT/HOLD/REJECT means hold whatever's already there, not liquidate it
    else:
        # A BUY/SELL with 0 approved_allocation (e.g. a forced square-off
        # closing trade) is not "no change" -- target_notional correctly
        # comes out to 0 either way, same formula, no special-casing needed.
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
    new_qty = current_qty + delta_qty
    portfolio.positions[consensus.symbol] = new_qty
    _update_entry_price(portfolio, consensus.symbol, current_qty, new_qty, delta_qty, price)

    return TradeRecord(
        symbol=consensus.symbol,
        action=trade_action,
        qty=trade_qty,
        price=price,
        cost_breakdown=cost_breakdown,
        net_cash_flow=net_cash_flow,
    )
