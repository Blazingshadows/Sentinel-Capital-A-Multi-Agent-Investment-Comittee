"""Volume / order-flow proxy signals -- the closest a retail OHLCV feed gets
to reading order-book pressure. Pure pandas, causal.
"""

import pandas as pd


def volume_zscore(ohlcv: pd.DataFrame, window: int = 20) -> pd.Series:
    """How unusual current volume is vs. its own recent history -- a spike
    often precedes or accompanies a real move rather than noise."""
    volume = ohlcv["Volume"]
    mean = volume.rolling(window).mean()
    std = volume.rolling(window).std().replace(0, float("nan"))
    return (volume - mean) / std


def obv_slope(ohlcv: pd.DataFrame, window: int = 10) -> pd.Series:
    """On-Balance Volume's rate of change over `window` bars -- whether
    volume is net accumulating or distributing, independent of price alone."""
    closes, volume = ohlcv["Close"], ohlcv["Volume"]
    direction = closes.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv = (direction * volume).cumsum()
    return obv.diff(periods=window) / volume.rolling(window).sum().replace(0, float("nan"))


def vwap_deviation(ohlcv: pd.DataFrame, window: int = 20) -> pd.Series:
    """Close vs. a rolling volume-weighted average price -- positive means
    trading above where the recent volume-weighted flow has been."""
    closes, volume = ohlcv["Close"], ohlcv["Volume"]
    rolling_vwap = (closes * volume).rolling(window).sum() / volume.rolling(window).sum().replace(0, float("nan"))
    return (closes - rolling_vwap) / rolling_vwap
