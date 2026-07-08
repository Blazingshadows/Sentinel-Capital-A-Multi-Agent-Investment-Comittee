"""Session-level P&L reporting — the Audit Layer's summary view. The PS
requires reporting *net* profit after all trading costs, not gross; this
turns that from "re-derive it from raw trade rows" into one function call.

`gross_pnl = net_pnl + total_costs` rather than summing trade-by-trade cash
flows, because `net_pnl` already comes from mark-to-market portfolio value
(cash + open positions at current prices) — it correctly counts unrealized
P&L on positions still open, not just realized cash flow from closed
trades. Adding back the costs that were actually charged recovers the
counterfactual "what would P&L have been at zero cost" figure.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.committee.config import BUYING_POWER
from backend.committee.persistence import models


@dataclass
class PnLSummary:
    trade_count: int
    gross_pnl: float
    total_costs: float
    net_pnl: float
    growth_pct: float

    def __str__(self) -> str:
        return (
            f"Trades executed:     {self.trade_count}\n"
            f"Gross P&L:           {self.gross_pnl:+,.2f}\n"
            f"Total trading costs: {self.total_costs:,.2f}\n"
            f"Net P&L:             {self.net_pnl:+,.2f}\n"
            f"Growth:              {self.growth_pct:+.2f}%"
        )


def summarize_pnl(session: Session, portfolio_value: float, starting_capital: float = BUYING_POWER) -> PnLSummary:
    trades = session.query(models.Decision).filter(models.Decision.qty > 0).all()
    total_costs = sum((trade.cost_breakdown or {}).get("total_cost", 0.0) for trade in trades)

    net_pnl = portfolio_value - starting_capital
    gross_pnl = net_pnl + total_costs
    growth_pct = (net_pnl / starting_capital) * 100

    return PnLSummary(
        trade_count=len(trades),
        gross_pnl=gross_pnl,
        total_costs=total_costs,
        net_pnl=net_pnl,
        growth_pct=growth_pct,
    )


def cost_breakdown_by_symbol(session: Session) -> dict[str, dict]:
    """Diagnostic, not a P&L split: shared cash across symbols makes a fully
    rigorous per-symbol P&L attribution nontrivial. This just shows which
    symbols incurred the most trading-cost drag, by trade count and total
    cost paid.
    """
    trades = session.query(models.Decision).filter(models.Decision.qty > 0).all()
    breakdown: dict[str, dict] = {}
    for trade in trades:
        entry = breakdown.setdefault(trade.stock, {"trade_count": 0, "total_costs": 0.0})
        entry["trade_count"] += 1
        entry["total_costs"] += (trade.cost_breakdown or {}).get("total_cost", 0.0)
    return breakdown
