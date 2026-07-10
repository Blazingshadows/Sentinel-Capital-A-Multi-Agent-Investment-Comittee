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

from backend.committee.config import INTRADAY_BARS_PER_DAY, WATCHLIST
from backend.committee.execution.portfolio import Portfolio
from backend.committee.market_data.context import MarketContext, fetch_fundamentals
from backend.committee.market_data.news import fetch_headlines
from backend.committee.market_data.prices import cache_path, fetch_ohlcv
from backend.committee.orchestration.cycle import process_context
from backend.committee.orchestration.loop import run_watchlist_once
from backend.committee.schemas import DecisionLog, Suggestion

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
    """Single-symbol replay -- bypasses the cross-symbol allocator entirely
    (there's only ever one symbol in play), so this is a reasonable tool for
    inspecting one stock's behavior in isolation, but NOT a substitute for
    `run_replay_session` below when demoing the full committee: an earlier
    version of watchlist-wide replay called this per symbol in a loop, which
    let positions size against the full BUYING_POWER as if each symbol had
    exclusive claim to it -- the same bug the live cross-symbol allocator
    exists to prevent, just reintroduced on the replay path. Kept here for
    single-symbol inspection only; see run_replay_session for anything that
    touches the shared portfolio across multiple symbols."""
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


def _build_feed(symbol: str, interval: str) -> ReplayFeed:
    ohlcv = load_cached_ohlcv(symbol, interval=interval)
    try:
        headlines = fetch_headlines(symbol)
    except Exception:
        headlines = []
    fundamentals, sector = fetch_fundamentals(symbol)
    return ReplayFeed(symbol=symbol, ohlcv=ohlcv, headlines=headlines, fundamentals=fundamentals, sector=sector)


async def run_replay_session(session_factory, portfolio: Portfolio, watchlist: list[str] = WATCHLIST,
                              interval: str = "5m", max_bars: int = INTRADAY_BARS_PER_DAY,
                              seconds_per_tick: float = 5.0, use_discovery: bool = True,
                              progress: dict | None = None, execution_mode: str = "autonomous",
                              suggestions: dict[str, Suggestion] | None = None) -> None:
    """Demo entrypoint for outside market hours: one `ReplayFeed` per
    watchlist symbol, advanced in lockstep -- every tick pulls the next
    cached bar for *every* symbol at once and runs them through
    `run_watchlist_once` exactly as a live cycle would, so the cross-symbol
    allocator, stop-loss, and Alternative-Stocks/SWITCH comparison all see
    the same one-cycle-many-symbols view they do live, not a per-symbol
    replay bypassing them. Runs until `max_bars` ticks, the earliest-
    exhausted symbol's cache runs out, or the caller's asyncio Task is
    cancelled -- mirrors `run_session`'s cancellation contract exactly, so
    the API layer can start/stop it the same way.

    `use_discovery=True` runs Opportunity Discovery once up front, same as
    a live session, so a demo replay exercises the same watchlist-selection
    path being judged rather than a fixed 10-symbol list.

    Each tick's `run_watchlist_once` call runs via `asyncio.to_thread` --
    it's synchronous and makes real LLM calls, so calling it directly here
    would block this coroutine's event loop for the whole tick, starving a
    concurrent progress poll until the tick finished instead of just until
    the next `await`.

    `execution_mode`/`suggestions` pass straight through to
    `run_watchlist_once` -- see its docstring. In manual mode a symbol's
    suggestion naturally gets superseded by its own next tick here, same as
    a live session's next cycle."""
    session_watchlist = watchlist
    if use_discovery:
        from backend.committee.orchestration.watchlist import select_session_watchlist

        session_watchlist = select_session_watchlist(progress)

    feeds: dict[str, ReplayFeed] = {}
    for symbol in session_watchlist:
        try:
            feeds[symbol] = _build_feed(symbol, interval)
        except Exception:
            logger.exception("Replay feed setup failed for %s -- excluded from this replay session.", symbol)

    active_watchlist = [symbol for symbol in session_watchlist if symbol in feeds]
    if not active_watchlist:
        logger.error("No symbols had usable cached data -- replay session has nothing to play.")
        if progress is not None:
            progress["phase"] = "error"
            progress["detail"] = "No symbols had usable cached data for replay."
        return

    if progress is not None:
        progress["max_bars"] = max_bars
        progress["bars_played"] = 0

    bars_played = 0
    while bars_played < max_bars and all(feeds[symbol].has_next() for symbol in active_watchlist):
        contexts_this_tick = {symbol: feeds[symbol].next_context() for symbol in active_watchlist}
        session = session_factory()
        try:
            await asyncio.to_thread(
                run_watchlist_once, session, portfolio, active_watchlist,
                context_provider=lambda s: contexts_this_tick[s], progress=progress,
                execution_mode=execution_mode, suggestions=suggestions,
                session_factory=session_factory,
            )
        except Exception:
            logger.exception("Replay tick failed.")
        finally:
            session.close()
        bars_played += 1
        if progress is not None:
            progress["bars_played"] = bars_played
        if seconds_per_tick:
            await asyncio.sleep(seconds_per_tick)
