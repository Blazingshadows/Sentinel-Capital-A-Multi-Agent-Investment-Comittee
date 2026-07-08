"""Volatility-regime signals -- the options-market-maker / vol-risk-premium
style (Jane Street-adjacent): what the market's realized volatility is doing
right now, independent of direction. Pure pandas, causal.
"""

import pandas as pd


def realized_vol_ratio(ohlcv: pd.DataFrame, short: int = 5, long: int = 20) -> pd.Series:
    """Short-window realized vol over long-window realized vol -- >1 means
    volatility is expanding relative to its recent baseline."""
    returns = ohlcv["Close"].pct_change()
    vol_short = returns.rolling(short).std()
    vol_long = returns.rolling(long).std().replace(0, float("nan"))
    return vol_short / vol_long


def atr_normalized(ohlcv: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range normalized by close, so it's comparable across
    stocks at different price levels."""
    high, low, close = ohlcv["High"], ohlcv["Low"], ohlcv["Close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = true_range.rolling(period).mean()
    return atr / close


def atr_expansion(ohlcv: pd.DataFrame, short: int = 5, long: int = 20) -> pd.Series:
    """Ratio of short-window ATR to long-window ATR -- flags a volatility
    breakout distinct from `realized_vol_ratio`'s close-to-close measure
    (this one captures intrabar range, not just bar-to-bar drift)."""
    atr_short = atr_normalized(ohlcv, short)
    atr_long = atr_normalized(ohlcv, long).replace(0, float("nan"))
    return atr_short / atr_long
