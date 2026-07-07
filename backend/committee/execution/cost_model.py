"""NSE intraday equity retail cost model — pure deterministic arithmetic, no
dependency on live data. Every simulated fill pays these costs so "profit
after all trading costs" is a real number, not an approximation."""

from backend.committee.config import (
    BROKERAGE_FLAT_CAP,
    BROKERAGE_PCT,
    EXCHANGE_TXN_PCT,
    GST_PCT,
    SEBI_CHARGE_PER_CRORE,
    SLIPPAGE_PCT_RANGE,
    STAMP_DUTY_PCT,
    STT_PCT,
)
from backend.committee.schemas import CostBreakdown, Decision

CRORE = 10_000_000


def apply_costs(action: Decision, qty: float, price: float) -> tuple[float, CostBreakdown]:
    """Only meaningful for BUY/SELL. Returns (net_cash_flow, breakdown) where
    net_cash_flow is negative for a BUY (cash out) and positive for a SELL
    (cash in), net of every cost component."""
    turnover = qty * price

    brokerage = min(BROKERAGE_FLAT_CAP, BROKERAGE_PCT * turnover)
    stt = STT_PCT * turnover if action == Decision.SELL else 0.0
    exchange_txn_charges = EXCHANGE_TXN_PCT * turnover
    sebi_charges = SEBI_CHARGE_PER_CRORE * (turnover / CRORE)
    stamp_duty = STAMP_DUTY_PCT * turnover if action == Decision.BUY else 0.0
    gst = GST_PCT * (brokerage + exchange_txn_charges)
    slippage = (sum(SLIPPAGE_PCT_RANGE) / 2) * turnover

    breakdown = CostBreakdown(
        brokerage=brokerage,
        stt=stt,
        exchange_txn_charges=exchange_txn_charges,
        sebi_charges=sebi_charges,
        stamp_duty=stamp_duty,
        gst=gst,
        slippage=slippage,
    )

    net_cash_flow = (-turnover if action == Decision.BUY else turnover) - breakdown.total_cost
    return net_cash_flow, breakdown
