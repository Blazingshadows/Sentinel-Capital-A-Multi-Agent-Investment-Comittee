"""OHLCV ingestion for the watchlist. Live pulls are cached to
`data/historical/` so a network hiccup (or Replay Mode, see
`backend/committee/replay/`) can fall back to the last good pull."""

from pathlib import Path

import pandas as pd
import yfinance as yf

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "historical"


def _cache_path(symbol: str, interval: str) -> Path:
    return DATA_DIR / f"{symbol}_{interval}.csv"


def fetch_ohlcv(symbol: str, period: str = "60d", interval: str = "5m", use_cache_on_failure: bool = True) -> pd.DataFrame:
    """Pulls OHLCV for `symbol` (NSE, `.NS` suffix added automatically).

    Falls back to the last cached pull for this symbol/interval if the live
    fetch fails or returns empty (rate limit, no network, market closed with
    no recent bars) — the caller always gets a DataFrame or a clear error,
    never a silent empty result mistaken for "no signal".
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(symbol, interval)

    try:
        df = yf.download(f"{symbol}.NS", period=period, interval=interval, progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError(f"empty OHLCV response for {symbol}")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.to_csv(cache_path)
        return df
    except Exception:
        if use_cache_on_failure and cache_path.exists():
            return pd.read_csv(cache_path, index_col=0, parse_dates=True)
        raise


def latest_price(ohlcv: pd.DataFrame) -> float:
    return float(ohlcv["Close"].iloc[-1])
