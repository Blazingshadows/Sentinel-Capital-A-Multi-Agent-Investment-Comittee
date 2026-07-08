"""OHLCV ingestion for the watchlist, sourced from ICICI Direct's Breeze API
(see `breeze_client.py`). Live pulls are cached to `data/historical/` so a
network hiccup (or Replay Mode, see `backend/committee/replay/`) can fall
back to the last good pull.

The cache *accumulates* across calls rather than being overwritten each
time. This mattered most under yfinance's 60-day intraday cap; Breeze itself
allows a much longer lookback (get_historical_data_v2 is good for ~3 years),
but accumulation is still cheap insurance against thinning that window out
by re-requesting it every call.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from backend.committee.market_data import breeze_client

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "historical"


def _period_to_range(period: str) -> tuple[datetime, datetime]:
    """Parses a "60d"/"180d"-style period string into a (from, to) range
    ending now, matching the convention every caller already passes."""
    match = re.fullmatch(r"(\d+)d", period)
    if not match:
        raise ValueError(f"unsupported period format: {period!r} (expected e.g. '60d')")
    days = int(match.group(1))
    to_date = datetime.now()
    return to_date - timedelta(days=days), to_date


def cache_path(symbol: str, interval: str) -> Path:
    return DATA_DIR / f"{symbol}_{interval}.csv"


def _merge_with_cache(new_df: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Newer rows win on overlapping timestamps (a re-fetched bar is treated
    as a correction), everything else is unioned in, so history accumulates
    instead of being replaced on every call."""
    if not path.exists():
        return new_df.sort_index()
    try:
        existing = pd.read_csv(path, index_col=0, parse_dates=True)
    except Exception:
        return new_df.sort_index()
    combined = pd.concat([existing, new_df])
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


def fetch_ohlcv(symbol: str, period: str = "60d", interval: str = "5m", use_cache_on_failure: bool = True) -> pd.DataFrame:
    """Pulls OHLCV for `symbol` from Breeze (NSE; see `config.BREEZE_STOCK_CODE_MAP`
    for the symbol -> Breeze stock_code translation).

    Falls back to the last cached pull for this symbol/interval if the live
    fetch fails or returns empty (rate limit, no network, market closed with
    no recent bars) — the caller always gets a DataFrame or a clear error,
    never a silent empty result mistaken for "no signal". On success, returns
    the full accumulated cache (this fetch's window merged with everything
    seen before), not just the freshly-fetched window.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = cache_path(symbol, interval)

    try:
        from_date, to_date = _period_to_range(period)
        df = breeze_client.fetch_historical_ohlcv(symbol, from_date, to_date, interval=interval)
        if df.empty:
            raise ValueError(f"empty OHLCV response for {symbol}")
        merged = _merge_with_cache(df, path)
        merged.to_csv(path)
        return merged
    except Exception:
        if use_cache_on_failure and path.exists():
            return pd.read_csv(path, index_col=0, parse_dates=True)
        raise


def latest_price(ohlcv: pd.DataFrame) -> float:
    return float(ohlcv["Close"].iloc[-1])
