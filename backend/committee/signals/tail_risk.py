"""Tail-risk / exhaustion signals -- the Burry-style contrarian read: spot
capitulation and blow-off-top setups rather than trade with the crowd. Pure
pandas, causal.
"""

import pandas as pd

from backend.committee.agents.technical import compute_rsi


def drawdown_from_high(ohlcv: pd.DataFrame, window: int = 50) -> pd.Series:
    """How far below its own `window`-bar high the close currently sits
    (<=0). A large drawdown is either a real breakdown or a capitulation
    setup -- the model, not this feature, decides which."""
    closes = ohlcv["Close"]
    rolling_high = closes.rolling(window).max()
    return closes / rolling_high - 1.0


def exhaustion_flag(ohlcv: pd.DataFrame, rsi_period: int = 14, vol_window: int = 20) -> pd.Series:
    """RSI extremity amplified by a volume climax -- a large move on unusually
    heavy volume is the classic capitulation/blow-off signature, versus the
    same RSI reading on ordinary volume."""
    rsi_centered = (compute_rsi(ohlcv["Close"], rsi_period) - 50.0) / 50.0
    volume = ohlcv["Volume"]
    vol_mean = volume.rolling(vol_window).mean()
    vol_std = volume.rolling(vol_window).std().replace(0, float("nan"))
    volume_z = ((volume - vol_mean) / vol_std).clip(lower=0)
    return rsi_centered * volume_z


def gap_fade(ohlcv: pd.DataFrame) -> pd.Series:
    """Bar-open gap vs. the prior bar's close -- large gaps tend to partially
    fade, a classic overreaction/reflexivity setup."""
    prev_close = ohlcv["Close"].shift(1)
    return (ohlcv["Open"] - prev_close) / prev_close
