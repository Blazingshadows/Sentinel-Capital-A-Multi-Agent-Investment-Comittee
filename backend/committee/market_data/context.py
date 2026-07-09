"""Unified market context object — the Market Data Layer's single output,
consumed by every specialist agent so none of them re-fetch data
independently."""

from dataclasses import dataclass, field

import pandas as pd

from backend.committee.config import WATCHLIST_FUNDAMENTALS
from backend.committee.market_data.news import fetch_headlines
from backend.committee.market_data.prices import fetch_ohlcv


@dataclass
class MarketContext:
    symbol: str
    ohlcv: pd.DataFrame
    headlines: list[str]
    fundamentals: dict
    sector: str | None
    context_flags: list[str] = field(default_factory=list)

    @property
    def latest_price(self) -> float:
        return float(self.ohlcv["Close"].iloc[-1])


_discovery_sector_map: dict[str, str | None] | None = None


def _discovery_sector(symbol: str) -> str | None:
    """Discovery's universe file covers 229 symbols' sectors (no marketCap)
    -- a real fallback for symbols outside the small hand-maintained
    WATCHLIST_FUNDAMENTALS table, e.g. anything Discovery selects beyond the
    original fixed 10. Loaded once and cached at module level rather than
    re-reading the universe JSON on every agent call."""
    global _discovery_sector_map
    if _discovery_sector_map is None:
        from backend.committee.discovery.universe import load_sector_map

        try:
            _discovery_sector_map = load_sector_map()
        except Exception:
            _discovery_sector_map = {}
    return _discovery_sector_map.get(symbol)


def fetch_fundamentals(symbol: str) -> tuple[dict, str | None]:
    """Breeze is a trading/quotes API with no fundamentals or sector data --
    unlike yfinance's `.info`, so this looks up a small static table for the
    original fixed watchlist first, falling back to Discovery's broader
    sector map (marketCap has no such fallback -- not tracked there).
    Symbols in neither degrade to an empty fundamentals dict rather than
    aborting the whole cycle."""
    info = WATCHLIST_FUNDAMENTALS.get(symbol, {})
    sector = info.get("sector") or _discovery_sector(symbol)
    return info, sector


def build_context(symbol: str, period: str = "60d", interval: str = "5m", news_limit: int = 10,
                   context_flags: list[str] | None = None) -> MarketContext:
    ohlcv = fetch_ohlcv(symbol, period=period, interval=interval)
    headlines = fetch_headlines(symbol, limit=news_limit)
    fundamentals, sector = fetch_fundamentals(symbol)
    return MarketContext(
        symbol=symbol,
        ohlcv=ohlcv,
        headlines=headlines,
        fundamentals=fundamentals,
        sector=sector,
        context_flags=context_flags or ["normal"],
    )
