"""Indicator helpers for Opportunity Discovery.

**Reuse first**: RSI/EMA/MACD are imported from `agents/technical.py`, not
reimplemented. This module adds only what the codebase lacks — ATR, ADX,
realized volatility, robust relative volume, Kaufman efficiency ratio,
information-ratio (risk-adjusted) momentum, vol-expansion ratio, EMA-stretch,
and range position. All pure and vectorized over an OHLCV frame.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.committee.agents.technical import compute_ema, compute_macd, compute_rsi

__all__ = [
    "compute_ema", "compute_macd", "compute_rsi",
    "true_range", "average_true_range", "atr_percent",
    "average_directional_index", "realized_volatility", "relative_volume",
    "efficiency_ratio", "risk_adjusted_momentum", "blended_momentum",
    "vol_expansion_ratio", "ema_stretch_atr", "range_position",
    "trend_slope", "gap_pct",
]


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    ranges = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1)
    return ranges.max(axis=1)


def average_true_range(ohlcv: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = true_range(ohlcv["High"], ohlcv["Low"], ohlcv["Close"])
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def atr_percent(ohlcv: pd.DataFrame, period: int = 14) -> float:
    close = ohlcv["Close"]
    atr = average_true_range(ohlcv, period)
    last_close = float(close.iloc[-1])
    last_atr = float(atr.iloc[-1])
    if not np.isfinite(last_atr) or last_close <= 0:
        return 0.0
    return last_atr / last_close


def average_directional_index(ohlcv: pd.DataFrame, period: int = 14) -> pd.Series:
    """ADX (Wilder). Trend *strength* 0-100, direction-agnostic."""
    high, low, close = ohlcv["High"], ohlcv["Low"], ohlcv["Close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=ohlcv.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=ohlcv.index)
    tr = true_range(high, low, close)
    atr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / atr
        minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / atr
        di_sum = (plus_di + minus_di).replace(0, np.nan)
        dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    return dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def _log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1)).dropna()


def realized_volatility(close: pd.Series, window: int, bars_per_year: int) -> float:
    """Annualized realized volatility from the last `window` log returns."""
    returns = _log_returns(close)
    if len(returns) < window:
        return 0.0
    return float(returns.iloc[-window:].std(ddof=1) * np.sqrt(bars_per_year))


def _per_bar_vol(close: pd.Series, window: int) -> float:
    returns = _log_returns(close)
    if len(returns) < 2:
        return 0.0
    recent = returns.iloc[-window:] if len(returns) >= window else returns
    return float(recent.std(ddof=1))


def relative_volume(volume: pd.Series, window: int, recent_window: int = 1) -> float:
    """Mean volume over the last `recent_window` bars / trailing median over
    `window` bars. Averaging the recent bars (instead of a single, possibly
    partial, live bar) reduces partial-bar noise. 1.0 = an average session."""
    if len(volume) < 2:
        return 1.0
    trailing = volume.iloc[-(window + 1):-1] if len(volume) > window else volume.iloc[:-1]
    median = float(trailing.median())
    recent = float(volume.iloc[-recent_window:].mean())
    if median <= 0 or not np.isfinite(median):
        return 1.0
    return recent / median


def efficiency_ratio(close: pd.Series, window: int) -> float:
    """Kaufman efficiency ratio over the last `window` bars: |net move| / sum
    of |bar moves|, in [0,1]. 1 = a perfectly clean trend, ~0 = choppy noise.
    A cheaper, less-laggy trend-quality read than ADX."""
    if len(close) <= window:
        return 0.0
    segment = close.iloc[-(window + 1):]
    net = abs(float(segment.iloc[-1]) - float(segment.iloc[0]))
    path = float(segment.diff().abs().sum())
    if path <= 0 or not np.isfinite(path):
        return 0.0
    return net / path


def blended_momentum(close: pd.Series, lookbacks: list[int]) -> float:
    """Signed average of multi-horizon simple returns (raw, for reporting)."""
    values = []
    for n in lookbacks:
        if len(close) > n:
            past = float(close.iloc[-(n + 1)])
            if past > 0:
                values.append(float(close.iloc[-1]) / past - 1.0)
    return float(np.mean(values)) if values else 0.0


def risk_adjusted_momentum(close: pd.Series, lookbacks: list[int], vol_window: int) -> float:
    """Information-ratio momentum: each horizon's log return divided by its
    expected volatility (per-bar vol * sqrt(horizon)), then averaged. This
    (a) risk-adjusts — a 2% move in a 1%-vol name outranks the same move in a
    5%-vol name — and (b) equalizes horizon scale, so the longest lookback no
    longer dominates the blend. Signed."""
    per_bar = _per_bar_vol(close, vol_window)
    if per_bar <= 0:
        return 0.0
    ratios = []
    for n in lookbacks:
        if len(close) > n:
            past = float(close.iloc[-(n + 1)])
            last = float(close.iloc[-1])
            if past > 0 and last > 0:
                ret = np.log(last / past)
                ratios.append(ret / (per_bar * np.sqrt(n)))
    return float(np.mean(ratios)) if ratios else 0.0


def vol_expansion_ratio(close: pd.Series, short_window: int, long_window: int) -> float:
    """Short-window realized vol / long-window realized vol. >1 means volatility
    is *expanding from a quiet base* (a waking-up stock — the tradeable setup),
    which is what 'volatility opportunity' should measure, not raw vol level."""
    short_v = _per_bar_vol(close, short_window)
    long_v = _per_bar_vol(close, long_window)
    if long_v <= 0 or not np.isfinite(long_v):
        return 1.0
    return short_v / long_v


def ema_stretch_atr(ohlcv: pd.DataFrame, span: int, atr_period: int) -> float:
    """Signed distance of price from its EMA in ATR units — a mean-reversion
    stretch measure. Large |value| = extended, prone to snap back."""
    close = ohlcv["Close"]
    ema = compute_ema(close, span)
    atr = average_true_range(ohlcv, atr_period)
    last_atr = float(atr.iloc[-1])
    if not np.isfinite(last_atr) or last_atr <= 0:
        return 0.0
    return (float(close.iloc[-1]) - float(ema.iloc[-1])) / last_atr


def range_position(close: pd.Series, window: int) -> float:
    """(close - min) / (max - min) over the last `window` bars, in [0,1].
    Near 1 = pressing the highs (breakout), near 0 = pressing the lows."""
    if len(close) < window:
        window = len(close)
    segment = close.iloc[-window:]
    lo, hi = float(segment.min()), float(segment.max())
    if hi - lo <= 0 or not np.isfinite(hi - lo):
        return 0.5
    return (float(close.iloc[-1]) - lo) / (hi - lo)


def trend_slope(close: pd.Series, fast: int, slow: int) -> float:
    ema_fast = compute_ema(close, fast)
    ema_slow = compute_ema(close, slow)
    denom = float(ema_slow.iloc[-1])
    if denom <= 0 or not np.isfinite(denom):
        return 0.0
    return (float(ema_fast.iloc[-1]) - denom) / denom


def gap_pct(ohlcv: pd.DataFrame) -> float:
    if len(ohlcv) < 2:
        return 0.0
    prev_close = float(ohlcv["Close"].iloc[-2])
    last_open = float(ohlcv["Open"].iloc[-1])
    if prev_close <= 0:
        return 0.0
    return last_open / prev_close - 1.0
