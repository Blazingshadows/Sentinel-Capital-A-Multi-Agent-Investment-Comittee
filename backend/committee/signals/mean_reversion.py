"""Short-horizon mean-reversion signals -- the stat-arb / market-making-
adjacent style (how Citadel/Jane Street-type desks trade at this timescale):
fade extremes rather than chase them. Pure pandas, causal.
"""

import pandas as pd

from backend.committee.agents.technical import compute_rsi


def rsi_deviation(ohlcv: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI recentred around 0: positive = overbought, negative = oversold."""
    return (compute_rsi(ohlcv["Close"], period) - 50.0) / 50.0


def zscore_price(ohlcv: pd.DataFrame, window: int = 20) -> pd.Series:
    """Rolling z-score of close vs. its own recent mean -- how stretched the
    price is from its local average, in standard-deviation units."""
    closes = ohlcv["Close"]
    mean = closes.rolling(window).mean()
    std = closes.rolling(window).std().replace(0, float("nan"))
    return (closes - mean) / std


def bollinger_pctb(ohlcv: pd.DataFrame, window: int = 20, num_std: float = 2.0) -> pd.Series:
    """%B: where close sits within the Bollinger band, 0 = lower band,
    1 = upper band (and beyond in either direction on a band breach)."""
    closes = ohlcv["Close"]
    mean = closes.rolling(window).mean()
    std = closes.rolling(window).std()
    upper = mean + num_std * std
    lower = mean - num_std * std
    band_width = (upper - lower).replace(0, float("nan"))
    return (closes - lower) / band_width


def short_reversal(ohlcv: pd.DataFrame, period: int = 3) -> pd.Series:
    """Raw short-horizon return -- a sharp recent move that mean-reversion
    strategies expect to partially retrace."""
    return ohlcv["Close"].pct_change(periods=period)
