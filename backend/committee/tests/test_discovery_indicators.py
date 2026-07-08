"""Tests for discovery indicators, including the new quant factors
(efficiency ratio, risk-adjusted momentum, vol-expansion, EMA-stretch,
range position) and reuse of the existing RSI/EMA/MACD primitives."""

import numpy as np
import pandas as pd

from backend.committee.discovery import indicators
from backend.committee.tests.discovery_synth import make_ohlcv


def _trend(direction: int, n: int = 120) -> pd.DataFrame:
    closes = 1000 + np.cumsum(np.full(n, direction * 2.0))
    index = pd.date_range("2026-01-01 09:15", periods=n, freq="5min")
    return pd.DataFrame({"Open": closes, "High": closes + 2, "Low": closes - 2, "Close": closes, "Volume": 10_000.0}, index=index)


def test_reused_primitives_are_the_technical_agents():
    from backend.committee.agents import technical

    assert indicators.compute_rsi is technical.compute_rsi
    assert indicators.compute_ema is technical.compute_ema


def test_efficiency_ratio_high_for_clean_trend_low_for_chop():
    clean = _trend(1)["Close"]
    chop = make_ohlcv(seed=7, drift=0.0, vol=0.01)["Close"]
    assert indicators.efficiency_ratio(clean, 20) > 0.9
    assert indicators.efficiency_ratio(chop, 20) < 0.6


def test_risk_adjusted_momentum_normalizes_by_vol():
    """Same raw drift, different vol -> the calmer name has the larger
    risk-adjusted momentum (information ratio)."""
    calm = make_ohlcv(seed=1, drift=0.001, vol=0.002)["Close"]
    wild = make_ohlcv(seed=1, drift=0.001, vol=0.010)["Close"]
    ra_calm = indicators.risk_adjusted_momentum(calm, [3, 5, 10], 20)
    ra_wild = indicators.risk_adjusted_momentum(wild, [3, 5, 10], 20)
    assert ra_calm > ra_wild


def test_vol_expansion_ratio_detects_waking_up():
    rng = np.random.default_rng(0)
    quiet = rng.normal(0, 0.001, 60)
    loud = rng.normal(0, 0.012, 8)  # short burst so the long window still spans the quiet base
    closes = pd.Series(1000 * np.cumprod(1 + np.concatenate([quiet, loud])))
    assert indicators.vol_expansion_ratio(closes, 5, 20) > 1.2


def test_ema_stretch_and_range_position_bounds():
    df = make_ohlcv(seed=3, drift=0.002, vol=0.004)
    stretch = indicators.ema_stretch_atr(df, 20, 14)
    assert stretch > 0  # persistent uptrend -> price above EMA
    pos = indicators.range_position(df["Close"], 20)
    assert 0.0 <= pos <= 1.0


def test_relative_volume_recent_window_is_robust():
    vol = pd.Series([100.0] * 20 + [250.0, 350.0, 300.0])
    rv = indicators.relative_volume(vol, window=20, recent_window=3)
    assert 2.5 < rv < 3.5  # ~mean(250,350,300)/100


def test_indicators_safe_on_degenerate_series():
    flat = pd.DataFrame({c: [10.0] * 60 for c in ["Open", "High", "Low", "Close", "Volume"]})
    assert indicators.atr_percent(flat) == 0.0
    assert indicators.vol_expansion_ratio(flat["Close"], 5, 20) == 1.0
    assert indicators.efficiency_ratio(flat["Close"], 20) == 0.0
