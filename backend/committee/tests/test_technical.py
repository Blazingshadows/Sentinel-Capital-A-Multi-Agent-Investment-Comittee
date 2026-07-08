import numpy as np
import pandas as pd

from backend.committee.agents.technical import analyze
from backend.committee.market_data.context import MarketContext
from backend.committee.schemas import Decision
from backend.committee.tests.conftest import synthetic_ohlcv


def _trending_context(direction: int) -> MarketContext:
    n = 100
    closes = 1000 + np.cumsum(np.full(n, direction * 2.0))
    index = pd.date_range("2026-01-01 09:15", periods=n, freq="15min")
    ohlcv = pd.DataFrame({"Open": closes, "High": closes + 1, "Low": closes - 1, "Close": closes, "Volume": 10_000}, index=index)
    return MarketContext(symbol="TEST", ohlcv=ohlcv, headlines=[], fundamentals={}, sector=None, context_flags=["normal"])


def test_uptrend_yields_buy():
    output = analyze(_trending_context(direction=1))
    assert output.decision == Decision.BUY
    assert output.confidence > 0


def test_downtrend_yields_sell():
    output = analyze(_trending_context(direction=-1))
    assert output.decision == Decision.SELL
    assert output.confidence > 0


def test_insufficient_history_waits():
    ohlcv = synthetic_ohlcv(n=10)
    context = MarketContext(symbol="TEST", ohlcv=ohlcv, headlines=[], fundamentals={}, sector=None, context_flags=["normal"])
    output = analyze(context)
    assert output.decision == Decision.WAIT
    assert output.confidence == 0.0
