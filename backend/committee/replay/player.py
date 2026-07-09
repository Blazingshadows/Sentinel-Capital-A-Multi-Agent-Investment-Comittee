"""Replay Mode — README: "if your demo/judging slot falls outside market
hours, replay a recent day's bars at accelerated speed through the exact
same pipeline". Built as just an alternate `MarketContext` source behind
`orchestration.cycle.process_context` — not a separate pipeline, so nothing
downstream needs to know whether a cycle came from live data or replay.
"""

import asyncio
import logging
from dataclasses import dataclass

import pandas as pd
from sqlalchemy.orm import Session

from backend.committee.config import WATCHLIST
from backend.committee.execution.portfolio import Portfolio
from backend.committee.market_data.context import MarketContext, fetch_fundamentals
from backend.committee.market_data.news import fetch_headlines
from backend.committee.market_data.prices import cache_path, fetch_ohlcv
from backend.committee.orchestration.cycle import process_context
from backend.committee.schemas import DecisionLog

logger = logging.getLogger(__name__)


def load_cached_ohlcv(symbol: str, interval: str = "5m", period: str = "60d") -> pd.DataFrame:
    """Reads the on-disk cache populated by earlier live pulls; fetches once
    to populate it if this symbol/interval has never been pulled before."""
    path = cache_path(symbol, interval)
    if path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True)
    return fetch_ohlcv(symbol, period=period, interval=interval)


@dataclass
class ReplayFeed:
    symbol: str
    ohlcv: pd.DataFrame
    headlines: list[str]
    fundamentals: dict
    sector: str | None
    cursor: int = 50  # need enough history for the Technical agent's EMA50 before the first tick

    def has_next(self) -> bool:
        return self.cursor < len(self.ohlcv)

    def next_context(self) -> MarketContext:
        window = self.ohlcv.iloc[: self.cursor + 1]
        self.cursor += 1
        return MarketContext(
            symbol=self.symbol,
            ohlcv=window,
            headlines=self.headlines,
            fundamentals=self.fundamentals,
            sector=self.sector,
            context_flags=["normal"],
        )


async def run_replay(session: Session, portfolio: Portfolio, symbol: str, interval: str = "5m",
                      seconds_per_bar: float = 1.0, max_bars: int | None = None) -> list[DecisionLog]:
    ohlcv = load_cached_ohlcv(symbol, interval=interval)
    try:
        headlines = fetch_headlines(symbol)
    except Exception:
        headlines = []
    fundamentals, sector = fetch_fundamentals(symbol)

    feed = ReplayFeed(symbol=symbol, ohlcv=ohlcv, headlines=headlines, fundamentals=fundamentals, sector=sector)

    logs: list[DecisionLog] = []
    bars_played = 0
    while feed.has_next() and (max_bars is None or bars_played < max_bars):
        context = feed.next_context()
        cycle_ts = pd.Timestamp(context.ohlcv.index[-1]).to_pydatetime()
        log, _ = process_context(session, portfolio, context, cycle_ts=cycle_ts)
        logs.append(log)
        bars_played += 1
        if seconds_per_bar:
            await asyncio.sleep(seconds_per_bar)

    return logs


async def run_watchlist_replay(session: Session, portfolio: Portfolio, watchlist: list[str] = WATCHLIST,
                                interval: str = "5m", max_bars: int = 5) -> list[DecisionLog]:
    """Demo entrypoint: replays `max_bars` cached bars per watchlist symbol,
    back-to-back with no artificial delay, so a dashboard demo outside market
    hours doesn't depend on Breeze being reachable -- as long as each symbol
    already has a cache file from an earlier live pull. One symbol's cache
    being missing/corrupt shouldn't blank the rest of the demo, so failures
    are isolated per symbol (same pattern as run_watchlist_once)."""
    logs: list[DecisionLog] = []
    for symbol in watchlist:
        try:
            logs.extend(await run_replay(session, portfolio, symbol, interval=interval, seconds_per_bar=0, max_bars=max_bars))
        except Exception:
            logger.exception("Replay failed for %s — skipping.", symbol)
            continue
    return logs
