"""Orchestration loop: runs one committee cycle per watchlist stock, then
takes a single portfolio mark-to-market snapshot for the whole pass (a
shared `Portfolio` can hold positions across many stocks, so it only makes
sense to snapshot once all of them have a fresh price for this pass).
"""

import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.committee.config import SESSION_SQUARE_OFF, SESSION_START, WATCHLIST
from backend.committee.execution.portfolio import Portfolio
from backend.committee.orchestration.cycle import run_cycle
from backend.committee.persistence import repository
from backend.committee.schemas import DecisionLog

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")


def is_market_hours(now: datetime | None = None) -> bool:
    now = (now or datetime.now(IST)).astimezone(IST)
    start = time.fromisoformat(SESSION_START)
    end = time.fromisoformat(SESSION_SQUARE_OFF)
    return start <= now.time() <= end


def run_watchlist_once(session: Session, portfolio: Portfolio, watchlist: list[str] = WATCHLIST,
                        context_flags: list[str] | None = None) -> list[DecisionLog]:
    logs: list[DecisionLog] = []
    latest_prices: dict[str, float] = {}

    for symbol in watchlist:
        try:
            log, price = run_cycle(session, portfolio, symbol, context_flags)
            logs.append(log)
            latest_prices[symbol] = price
        except Exception:
            logger.exception("Cycle failed for %s — skipping this stock this pass.", symbol)
            continue

    if latest_prices:
        snapshot = portfolio.mark_to_market(latest_prices)
        repository.insert_portfolio_snapshot(session, snapshot)

    return logs


async def run_forever(session_factory, watchlist: list[str] = WATCHLIST, interval_seconds: int = 300,
                       force_run_outside_market_hours: bool = False) -> None:
    """Asyncio loop, one watchlist pass every `interval_seconds` during NSE
    market hours. `force_run_outside_market_hours` exists for Replay Mode
    callers and local development, so the loop never has to be duplicated."""
    portfolio = Portfolio()
    while True:
        if force_run_outside_market_hours or is_market_hours():
            session = session_factory()
            try:
                run_watchlist_once(session, portfolio, watchlist)
            finally:
                session.close()
        await asyncio.sleep(interval_seconds)
