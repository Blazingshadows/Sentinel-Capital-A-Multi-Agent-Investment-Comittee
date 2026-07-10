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
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.committee.config import (
    BASE_EXPERTISE,
    COMMITTEE_EVAL_WORKERS,
    LIVE_SESSION_INTERVAL_SECONDS,
    SESSION_SQUARE_OFF,
    SESSION_START,
    STOP_LOSS_PCT,
    SWITCH_CONFIDENCE_MARGIN,
    SWITCH_MIN_CONFIDENCE,
    WATCHLIST,
)
from backend.committee.execution.portfolio import Portfolio
from backend.committee.market_data.context import MarketContext, build_context
from backend.committee.orchestration.allocator import AllocationCandidate, allocate_capital
from backend.committee.orchestration.cycle import finalize_cycle, run_specialists
from backend.committee.persistence import repository
from backend.committee.risk import manager as risk_manager
from backend.committee.schemas import (
    AlternativeCandidate,
    ConsensusDecision,
    DebateResult,
    Decision,
    DecisionLog,
    RiskAction,
    RiskVerdict,
    Suggestion,
)
from backend.committee.trust.scoring import refresh_trust_scores

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")


def is_market_hours(now: datetime | None = None) -> bool:
    now = (now or datetime.now(IST)).astimezone(IST)
    start = time.fromisoformat(SESSION_START)
    end = time.fromisoformat(SESSION_SQUARE_OFF)
    return start <= now.time() <= end


def _apply_stop_loss(evaluations: list[tuple], portfolio: Portfolio) -> list[tuple]:
    """Forces an exit when a held position's unrealized move against its
    cost basis breaches STOP_LOSS_PCT -- independent of, and prior to, the
    committee's own directional view for this cycle. Runs before cross-
    symbol comparison so a stop-loss breach is always a hard exit (BUY/SELL
    with 0 allocation, same target-zero mechanism as square-off), never
    left as a HOLD/WAIT that comparison could instead turn into a SWITCH."""
    updated = []
    for context, consensus, risk_verdict, revised in evaluations:
        qty = portfolio.positions.get(context.symbol, 0.0)
        entry_price = portfolio.entry_prices.get(context.symbol)
        if qty != 0 and entry_price:
            price = context.latest_price
            unrealized_pct = (price - entry_price) / entry_price * (1 if qty > 0 else -1)
            if unrealized_pct <= -STOP_LOSS_PCT:
                closing_decision = Decision.SELL if qty > 0 else Decision.BUY
                consensus = consensus.model_copy(
                    update={
                        "decision": closing_decision,
                        "confidence": 1.0,
                        "allocation": 0.0,
                        "reasoning": (
                            f"STOP-LOSS: {context.symbol} down {unrealized_pct:+.1%} vs cost basis "
                            f"{entry_price:.2f} (current {price:.2f}), breaching the -{STOP_LOSS_PCT:.0%} "
                            f"threshold -- forced exit overrides this cycle's consensus. "
                            f"Original reasoning: {consensus.reasoning}"
                        ),
                    }
                )
                risk_verdict = RiskVerdict(
                    action=RiskAction.APPROVE,
                    approved_allocation=0.0,
                    volatility_estimate=risk_verdict.volatility_estimate,
                    reason="Stop-loss triggered — forced exit, always approved regardless of volatility.",
                    expected_return=risk_verdict.expected_return,
                    expected_drawdown=risk_verdict.expected_drawdown,
                )
        updated.append((context, consensus, risk_verdict, revised))
    return updated


def _apply_cross_symbol_comparison(evaluations: list[tuple], portfolio: Portfolio) -> list[tuple]:
    """Ranks this cycle's candidates against each other -- only possible in a
    watchlist pass, where every symbol is evaluated together. Two things a
    single-symbol cycle structurally cannot do:

    1. Attach the top alternatives to every decision (PS-mandated
       "Alternative Stocks Considered" per-trade output).
    2. Upgrade a held-but-unconvinced position (HOLD/WAIT) to SWITCH when an
       unheld candidate both clears its own conviction bar and beats the
       held symbol's confidence by a real margin -- otherwise SWITCH would
       never fire, since nothing else in the pipeline compares symbols
       against each other.
    """
    ranked = sorted(evaluations, key=lambda e: e[1].confidence, reverse=True)

    updated = []
    for context, consensus, risk_verdict, revised in evaluations:
        alternatives = [
            AlternativeCandidate(symbol=c.symbol, decision=c.decision, confidence=c.confidence)
            for _, c, _, _ in ranked
            if c.symbol != context.symbol
        ][:2]
        consensus = consensus.model_copy(update={"alternatives": alternatives})

        current_qty = portfolio.positions.get(context.symbol, 0.0)
        if current_qty != 0 and consensus.decision in (Decision.HOLD, Decision.WAIT):
            best_alt = next(
                (
                    c
                    for _, c, _, _ in ranked
                    if c.symbol != context.symbol
                    and portfolio.positions.get(c.symbol, 0.0) == 0
                    and c.decision in (Decision.BUY, Decision.SELL)
                    and c.confidence >= SWITCH_MIN_CONFIDENCE
                    and c.confidence >= consensus.confidence + SWITCH_CONFIDENCE_MARGIN
                ),
                None,
            )
            if best_alt:
                consensus = consensus.model_copy(
                    update={
                        "decision": Decision.SWITCH,
                        "reasoning": (
                            f"SWITCH: {context.symbol} only reached {consensus.decision.value} conviction "
                            f"this cycle ({consensus.confidence:.2f}) while unheld {best_alt.symbol} shows "
                            f"stronger {best_alt.decision.value} conviction ({best_alt.confidence:.2f}) -- "
                            f"exiting {context.symbol} to free capital for it. Original reasoning: {consensus.reasoning}"
                        ),
                    }
                )
                risk_verdict = risk_manager.evaluate(context, consensus)

        updated.append((context, consensus, risk_verdict, revised))
    return updated


def run_watchlist_once(session: Session, portfolio: Portfolio, watchlist: list[str] = WATCHLIST,
                        context_flags: list[str] | None = None,
                        context_provider: Callable[[str], MarketContext] | None = None,
                        progress: dict | None = None, execution_mode: str = "autonomous",
                        suggestions: dict[str, Suggestion] | None = None,
                        session_factory: Callable[[], Session] | None = None,
                        max_workers: int = COMMITTEE_EVAL_WORKERS) -> list[DecisionLog]:
    """`context_provider(symbol) -> MarketContext` overrides the default live
    Breeze fetch -- Replay Mode's only hook into this function, so a replay
    pass runs through the *exact* same allocator/stop-loss/cross-symbol-
    comparison path a live pass does instead of a parallel implementation
    that could silently drift out of sync with it (or reintroduce the
    allocator-bypass bug an earlier, simpler Replay Mode had).

    Per-symbol data fetch and, separately, per-symbol agent evaluation each
    run on a bounded thread pool (`max_workers`) rather than one symbol at a
    time -- both are dominated by waiting on the network (a Breeze
    historical-data call; three different LLM providers' calls), so
    wall-clock time for a full pass scales down roughly linearly with worker
    count instead of linearly with watchlist size. Evaluation only
    parallelizes when `session_factory` is given, since each worker needs
    its own SQLAlchemy `Session` -- sharing one `Session` across threads is
    unsafe. Without it, evaluation falls back to fully sequential using the
    single `session` passed in. Prediction-outcome backfill and trust-score
    refresh happen once, sequentially, on the main `session` between the two
    parallel phases (previously redone from scratch for every single symbol
    -- redundant, and also a DB write that isn't safe to run concurrently).
    Execution afterwards stays fully sequential on `session`: it's cheap
    (no network/LLM calls) and, per-trade portfolio snapshots aside, this is
    also where the cross-symbol capital allocator's decisions get written,
    so keeping it single-threaded avoids ever needing to reason about
    concurrent writes to shared `portfolio` state.

    `progress`, if given, is mutated in place (current_symbol/
    symbols_completed/symbols_total) under a lock so a caller polling it
    from another coroutine (the API layer) can show real progress instead of
    the dashboard looking frozen for however long a full pass takes; with
    several symbols in flight at once, `current_symbol` reflects whichever
    one most recently finished, not a strict left-to-right march.

    `execution_mode="manual"` defers actionable decisions (BUY/SELL/SWITCH
    with nonzero approved allocation) instead of auto-executing them: each
    is written into `suggestions` (keyed by symbol, overwritten by that
    symbol's next cycle -- see Suggestion's docstring) for a human to
    execute later via the API layer's /suggestions/{symbol}/execute, which
    re-fetches a fresh price at click time rather than using the price this
    cycle evaluated at. HOLD/WAIT/rejected decisions have nothing to defer
    and always finalize immediately in both modes, clearing any stale
    suggestion for that symbol so it can't later be executed against a
    decision the committee has since moved off of."""
    cycle_ts = datetime.now(timezone.utc)
    fetch_context = context_provider or (lambda symbol: build_context(symbol, context_flags=context_flags))
    workers = max(1, max_workers)
    progress_lock = threading.Lock()

    def _bump_progress(symbol: str, verb: str) -> None:
        if progress is None:
            return
        with progress_lock:
            progress["current_symbol"] = symbol
            progress["symbols_completed"] += 1
            progress["detail"] = f"{verb} {symbol} ({progress['symbols_completed']}/{len(watchlist)})..."

    if progress is not None:
        progress["phase"] = "fetching"
        progress["symbols_total"] = len(watchlist)
        progress["symbols_completed"] = 0
        progress["detail"] = f"Fetching market data for {len(watchlist)} symbols..."

    contexts: dict[str, MarketContext] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_context, symbol): symbol for symbol in watchlist}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                contexts[symbol] = future.result()
            except Exception:
                logger.exception("Context fetch failed for %s — skipping this stock this pass.", symbol)
            _bump_progress(symbol, "Fetched")

    # Backfill is symbol-scoped (needs each symbol's just-fetched price) but
    # cheap and DB-only, so it stays a plain sequential loop; trust refresh
    # is committee-wide, so it only needs to run once per cycle, not once
    # per symbol.
    for symbol, context in contexts.items():
        repository.backfill_prediction_outcomes(session, symbol, before=cycle_ts, current_price=context.latest_price)
    refresh_trust_scores(session, list(BASE_EXPERTISE))

    if progress is not None:
        progress["phase"] = "evaluating"
        progress["symbols_completed"] = 0
        progress["detail"] = f"Evaluating {len(contexts)} symbols..."

    evaluations = []

    def _evaluate_one(symbol: str, context: MarketContext) -> tuple:
        worker_session = session_factory()
        try:
            current_position = portfolio.positions.get(symbol, 0.0)
            consensus, risk_verdict, revised_recommendations = run_specialists(worker_session, context, current_position)
            return context, consensus, risk_verdict, revised_recommendations
        finally:
            worker_session.close()

    if session_factory is not None:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_evaluate_one, symbol, context): symbol for symbol, context in contexts.items()}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    evaluations.append(future.result())
                except Exception:
                    logger.exception("Evaluation failed for %s — skipping this stock this pass.", symbol)
                _bump_progress(symbol, "Evaluated")
    else:
        for symbol, context in contexts.items():
            try:
                current_position = portfolio.positions.get(symbol, 0.0)
                consensus, risk_verdict, revised_recommendations = run_specialists(session, context, current_position)
                evaluations.append((context, consensus, risk_verdict, revised_recommendations))
            except Exception:
                logger.exception("Evaluation failed for %s — skipping this stock this pass.", symbol)
            _bump_progress(symbol, "Evaluated")

    evaluations = _apply_stop_loss(evaluations, portfolio)
    evaluations = _apply_cross_symbol_comparison(evaluations, portfolio)

    candidates = [
        AllocationCandidate(symbol=context.symbol, price=context.latest_price, consensus=consensus, risk_verdict=risk_verdict)
        for context, consensus, risk_verdict, _ in evaluations
    ]
    adjusted_verdicts = allocate_capital(candidates, portfolio)

    if progress is not None:
        progress["phase"] = "executing"
        progress["detail"] = "Executing approved trades..."

    logs: list[DecisionLog] = []
    # Seeded with every symbol evaluated this cycle *before* the execution
    # loop starts (not grown incrementally from only-already-executed
    # symbols) -- otherwise an early per-trade snapshot would price a
    # held-but-not-yet-processed-this-cycle position at 0 via
    # mark_to_market's prices.get(symbol, 0.0) fallback, understating
    # portfolio_value until that symbol's own turn came up later in the
    # same loop.
    latest_prices: dict[str, float] = {context.symbol: context.latest_price for context, _, _, _ in evaluations}

    for context, consensus, risk_verdict, revised_recommendations in evaluations:
        final_verdict = adjusted_verdicts.get(context.symbol, risk_verdict)

        is_actionable = (
            consensus.decision in (Decision.BUY, Decision.SELL, Decision.SWITCH)
            and final_verdict.action != RiskAction.REJECT
            and final_verdict.approved_allocation != 0
        )
        if execution_mode == "manual" and suggestions is not None:
            if is_actionable:
                suggestions[context.symbol] = Suggestion(
                    symbol=context.symbol,
                    consensus=consensus,
                    risk_verdict=final_verdict,
                    revised_recommendations=revised_recommendations,
                    suggested_price=context.latest_price,
                    suggested_at=datetime.now(timezone.utc),
                    cycle_ts=cycle_ts,
                )
                continue
            # HOLD/WAIT/rejected this cycle -- nothing to suggest, and any
            # earlier pending suggestion for this symbol is now stale.
            suggestions.pop(context.symbol, None)

        try:
            log = finalize_cycle(session, portfolio, context, consensus, final_verdict, revised_recommendations, cycle_ts)
        except Exception:
            logger.exception("Execution failed for %s — skipping this stock this pass.", context.symbol)
            continue
        logs.append(log)
        # Snapshot after every trade (not just once at the end of the pass)
        # so the dashboard's value-over-time chart visibly grows as trades
        # land instead of jumping once per whole cycle.
        snapshot = portfolio.mark_to_market(latest_prices)
        repository.insert_portfolio_snapshot(session, snapshot)

    if progress is not None:
        progress["phase"] = "idle"
        progress["current_symbol"] = None
        progress["detail"] = f"Cycle complete — {len(logs)} decision(s) processed."

    return logs


def square_off_all_positions(session: Session, portfolio: Portfolio) -> list[DecisionLog]:
    """Forces every open position flat -- PS: "All positions closed before
    market close." Bypasses the specialist agents entirely (this isn't a
    trading call, it's a mandatory session-end flatten) and constructs a
    direct closing decision per held symbol, executed through the normal
    cost model so a square-off trade pays the same realistic costs and
    leaves the same full audit trail as any other trade. Safe to call
    whenever -- symbols with no open position are a no-op."""
    cycle_ts = datetime.now(timezone.utc)
    logs: list[DecisionLog] = []
    held_symbols = [symbol for symbol, qty in list(portfolio.positions.items()) if qty != 0]
    latest_prices: dict[str, float] = {}

    for symbol in held_symbols:
        try:
            context = build_context(symbol)
        except Exception:
            logger.exception("Square-off price fetch failed for %s — position stays open, will retry next check.", symbol)
            continue
        latest_prices[symbol] = context.latest_price

        qty = portfolio.positions.get(symbol, 0.0)
        closing_decision = Decision.SELL if qty > 0 else Decision.BUY
        consensus = ConsensusDecision(
            symbol=symbol,
            decision=closing_decision,
            confidence=1.0,
            allocation=0.0,  # 0 allocation -> execute() computes target_qty=0, i.e. fully flat
            reasoning="Forced end-of-day square-off — PS requires all positions closed before market close.",
            influence_breakdown=[],
            debate=DebateResult(original_recommendations=[], contrarian_challenge="", revised_recommendations=[]),
        )
        risk_verdict = RiskVerdict(
            action=RiskAction.APPROVE,
            approved_allocation=0.0,
            volatility_estimate=0.0,
            reason="Forced square-off exit — always approved, closing trades are never risk-blocked.",
        )
        try:
            log = finalize_cycle(session, portfolio, context, consensus, risk_verdict, [], cycle_ts)
        except Exception:
            logger.exception("Square-off execution failed for %s.", symbol)
            continue
        logs.append(log)

    if latest_prices:
        snapshot = portfolio.mark_to_market(latest_prices)
        repository.insert_portfolio_snapshot(session, snapshot)

    return logs


async def run_forever(session_factory, portfolio: Portfolio, watchlist: list[str] = WATCHLIST,
                       interval_seconds: int = LIVE_SESSION_INTERVAL_SECONDS,
                       force_run_outside_market_hours: bool = False,
                       use_discovery: bool = True, progress: dict | None = None,
                       execution_mode: str = "autonomous", suggestions: dict[str, Suggestion] | None = None,
                       stop_event: asyncio.Event | None = None) -> None:
    """Continuous live session: one watchlist pass every `interval_seconds`
    during NSE market hours, ending itself -- not actually running forever --
    the moment either condition hits:

    1. `stop_event` is set (the API layer's /session/stop, a user-initiated
       stop), checked right after every pass finishes rather than only at the
       end of the `interval_seconds` sleep, so a stop request lands within
       moments instead of waiting out however much of the sleep remains.
    2. The session crosses the `SESSION_SQUARE_OFF` (15:15 IST) boundary, or
       is started outside market hours to begin with -- either way, every
       open position is flattened (`square_off_all_positions`) and `progress`
       is left on the terminal phase "market_closed" so the caller can show
       that instead of silently going idle.

    `force_run_outside_market_hours` exists for Replay Mode callers and local
    development, so the loop never has to be duplicated -- it disables the
    market-hours gate entirely rather than just the square-off exit, since a
    replay session has no real trading-hours boundary to honor.

    `use_discovery=True` runs Opportunity Discovery once at session start to
    pick the actual traded watchlist (see orchestration/watchlist.py) --
    scored and diversified over the full live-fetchable NSE universe rather
    than the fixed fallback `WATCHLIST`, which is only used if Discovery is
    disabled or fails.

    `portfolio` is the caller's shared instance (the API layer's
    `app.state.portfolio`), not a fresh one built here -- other endpoints
    (`/portfolio`, `/report`) read that same object, so a locally-created
    Portfolio would silently desync the dashboard from what this loop is
    actually trading.

    Each pass runs via `asyncio.to_thread` -- `run_watchlist_once` is
    synchronous and makes real, multi-second LLM/market-data calls; calling
    it directly here would block this coroutine's event loop for the whole
    pass, starving any concurrent request (e.g. a progress poll) until the
    pass finishes instead of just until the next `await`."""
    session_watchlist = watchlist
    if use_discovery:
        from backend.committee.orchestration.watchlist import select_session_watchlist

        session_watchlist = select_session_watchlist(progress)

    def _stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    try:
        while not _stopped():
            if not force_run_outside_market_hours and not is_market_hours():
                # Either the session started outside market hours, or a prior
                # pass just crossed the square-off boundary -- either way,
                # flatten everything (a no-op for symbols with no open
                # position) and end the session rather than looping forever
                # doing nothing until the next trading day.
                session = session_factory()
                try:
                    await asyncio.to_thread(square_off_all_positions, session, portfolio)
                finally:
                    session.close()
                if progress is not None:
                    progress["phase"] = "market_closed"
                    progress["detail"] = (
                        f"Market closed (outside {SESSION_START}-{SESSION_SQUARE_OFF} IST) -- "
                        "session ended, all positions squared off."
                    )
                return

            session = session_factory()
            try:
                await asyncio.to_thread(
                    run_watchlist_once, session, portfolio, session_watchlist,
                    progress=progress, execution_mode=execution_mode, suggestions=suggestions,
                    session_factory=session_factory,
                )
            finally:
                session.close()

            if _stopped():
                break

            # Wakes early on a stop request instead of always sleeping out the
            # full interval before noticing one.
            if stop_event is not None:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(interval_seconds)

        if progress is not None:
            progress["phase"] = "stopped"
            progress["detail"] = "Live session stopped."
    except Exception:
        logger.exception("Live session crashed.")
        if progress is not None:
            progress["phase"] = "error"
            progress["detail"] = "Live session hit an unexpected error -- check server logs."
        raise
