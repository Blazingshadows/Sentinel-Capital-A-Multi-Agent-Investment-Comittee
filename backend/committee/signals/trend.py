"""Trend/momentum signals — the CTA/managed-futures style: ride a
directional move once it's established. Pure pandas, causal (each row uses
only data up to and including that row, or strictly earlier where noted).
"""

import pandas as pd

from backend.committee.agents.technical import compute_ema


def ema_cross(ohlcv: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.Series:
    """Normalized EMA(fast) - EMA(slow), so it's comparable across stocks at
    different price levels."""
    closes = ohlcv["Close"]
    ema_fast = compute_ema(closes, fast)
    ema_slow = compute_ema(closes, slow)
    return (ema_fast - ema_slow) / ema_slow


def donchian_breakout(ohlcv: pd.DataFrame, window: int = 20) -> pd.Series:
    """Where the close sits within the prior `window`-bar high/low channel,
    in [-1, 1]. Uses `shift(1)` before the rolling max/min so the channel is
    strictly prior bars -- otherwise "breakout above the N-bar high" would be
    trivially true on the bar that sets the high."""
    high, low, close = ohlcv["High"], ohlcv["Low"], ohlcv["Close"]
    prior_high = high.shift(1).rolling(window).max()
    prior_low = low.shift(1).rolling(window).min()
    channel_width = (prior_high - prior_low).replace(0, float("nan"))
    return ((close - prior_low) / channel_width - 0.5) * 2


def trend_slope(ohlcv: pd.DataFrame, window: int = 20) -> pd.Series:
    """Percent change of EMA(20) over `window` bars -- a smoothed trend
    strength/direction measure, less noisy than raw price slope."""
    ema = compute_ema(ohlcv["Close"], 20)
    return ema.pct_change(periods=window)
