"""Orchestration loop: evaluates every watchlist stock first (agents through
Risk, no capital committed), runs the results through the cross-symbol
capital allocator, then executes -- a single symbol's risk verdict has no
visibility into what capital other watchlist symbols want the same cycle,
so trades can't be executed until all of them are known. Takes a single
portfolio mark-to-market snapshot for the whole pass (a shared `Portfolio`
can hold positions across many stocks, so it only makes sense to snapshot
once all of them have a fresh price for this pass).
"""

import asyncio
import logging
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.committee.config import SESSION_SQUARE_OFF, SESSION_START, WATCHLIST
from backend.committee.execution.portfolio import Portfolio
from backend.committee.market_data.context import build_context
from backend.committee.orchestration.allocator import AllocationCandidate, allocate_capital
from backend.committee.orchestration.cycle import evaluate_context, finalize_cycle
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
    cycle_ts = datetime.now(timezone.utc)
    evaluations = []

    for symbol in watchlist:
        try:
            context = build_context(symbol, context_flags=context_flags)
            current_position = portfolio.positions.get(symbol, 0.0)
            consensus, risk_verdict, revised_recommendations = evaluate_context(session, context, cycle_ts, current_position)
            evaluations.append((context, consensus, risk_verdict, revised_recommendations))
        except Exception:
            logger.exception("Evaluation failed for %s — skipping this stock this pass.", symbol)
            continue

    candidates = [
        AllocationCandidate(symbol=context.symbol, price=context.latest_price, consensus=consensus, risk_verdict=risk_verdict)
        for context, consensus, risk_verdict, _ in evaluations
    ]
    adjusted_verdicts = allocate_capital(candidates, portfolio)

    logs: list[DecisionLog] = []
    latest_prices: dict[str, float] = {}

    for context, consensus, risk_verdict, revised_recommendations in evaluations:
        final_verdict = adjusted_verdicts.get(context.symbol, risk_verdict)
        try:
            log = finalize_cycle(session, portfolio, context, consensus, final_verdict, revised_recommendations, cycle_ts)
        except Exception:
            logger.exception("Execution failed for %s — skipping this stock this pass.", context.symbol)
            continue
        logs.append(log)
        latest_prices[context.symbol] = context.latest_price

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
