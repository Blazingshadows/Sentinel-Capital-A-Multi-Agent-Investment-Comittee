"""Unified market context object — the Market Data Layer's single output,
consumed by every specialist agent so none of them re-fetch data
independently."""

from dataclasses import dataclass, field

import pandas as pd
import yfinance as yf

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


def fetch_fundamentals(symbol: str) -> tuple[dict, str | None]:
    """`.info` is a slow, occasionally-flaky yfinance call — failures degrade
    to an empty fundamentals dict rather than aborting the whole cycle."""
    try:
        info = yf.Ticker(f"{symbol}.NS").info
        return info, info.get("sector")
    except Exception:
        return {}, None


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
