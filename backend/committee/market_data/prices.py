"""OHLCV ingestion for the watchlist. Live pulls are cached to
`data/historical/` so a network hiccup (or Replay Mode, see
`backend/committee/replay/`) can fall back to the last good pull.

The cache *accumulates* across calls rather than being overwritten each
time. yfinance's intraday `period` cap (60d) is a per-call window, not a
hard ceiling on how much history the cache can hold: each day's fetch
mostly overlaps the previous one but also slides the window forward by
roughly a day, so calling this repeatedly over weeks grows the effective
history well past 60 days for free — no paid data source needed.
"""

from pathlib import Path

import pandas as pd
import yfinance as yf

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "historical"


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
    """Pulls OHLCV for `symbol` (NSE, `.NS` suffix added automatically).

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
        df = yf.download(f"{symbol}.NS", period=period, interval=interval, progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError(f"empty OHLCV response for {symbol}")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        merged = _merge_with_cache(df, path)
        merged.to_csv(path)
        return merged
    except Exception:
        if use_cache_on_failure and path.exists():
            return pd.read_csv(path, index_col=0, parse_dates=True)
        raise


def latest_price(ohlcv: pd.DataFrame) -> float:
    return float(ohlcv["Close"].iloc[-1])
