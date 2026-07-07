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
from backend.committee.execution.cost_model import CRORE, apply_costs
from backend.committee.schemas import Decision


def test_buy_pays_stamp_duty_not_stt():
    net_cash_flow, breakdown = apply_costs(Decision.BUY, qty=10, price=1000.0)
    turnover = 10_000.0

    assert breakdown.stt == 0.0
    assert breakdown.stamp_duty == STAMP_DUTY_PCT * turnover
    assert breakdown.brokerage == min(BROKERAGE_FLAT_CAP, BROKERAGE_PCT * turnover)
    assert breakdown.exchange_txn_charges == EXCHANGE_TXN_PCT * turnover
    assert breakdown.sebi_charges == SEBI_CHARGE_PER_CRORE * (turnover / CRORE)
    assert breakdown.gst == GST_PCT * (breakdown.brokerage + breakdown.exchange_txn_charges)
    assert breakdown.slippage == (sum(SLIPPAGE_PCT_RANGE) / 2) * turnover
    assert net_cash_flow == -turnover - breakdown.total_cost


def test_sell_pays_stt_not_stamp_duty():
    _, breakdown = apply_costs(Decision.SELL, qty=10, price=1000.0)
    assert breakdown.stamp_duty == 0.0
    assert breakdown.stt == STT_PCT * 10_000.0


def test_brokerage_caps_at_flat_fee_for_large_turnover():
    _, breakdown = apply_costs(Decision.BUY, qty=10_000, price=1000.0)  # turnover = 1 crore
    assert breakdown.brokerage == BROKERAGE_FLAT_CAP
