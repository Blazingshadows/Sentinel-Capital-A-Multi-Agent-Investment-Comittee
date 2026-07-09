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

from backend.committee.config import (
    SESSION_SQUARE_OFF,
    SESSION_START,
    STOP_LOSS_PCT,
    SWITCH_CONFIDENCE_MARGIN,
    SWITCH_MIN_CONFIDENCE,
    WATCHLIST,
)
from backend.committee.execution.portfolio import Portfolio
from backend.committee.market_data.context import build_context
from backend.committee.orchestration.allocator import AllocationCandidate, allocate_capital
from backend.committee.orchestration.cycle import evaluate_context, finalize_cycle
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
)

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

    evaluations = _apply_stop_loss(evaluations, portfolio)
    evaluations = _apply_cross_symbol_comparison(evaluations, portfolio)

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


async def run_forever(session_factory, watchlist: list[str] = WATCHLIST, interval_seconds: int = 300,
                       force_run_outside_market_hours: bool = False) -> None:
    """Asyncio loop, one watchlist pass every `interval_seconds` during NSE
    market hours. `force_run_outside_market_hours` exists for Replay Mode
    callers and local development, so the loop never has to be duplicated."""
    portfolio = Portfolio()
    was_market_hours = is_market_hours()
    while True:
        now_market_hours = is_market_hours()
        if force_run_outside_market_hours or now_market_hours:
            session = session_factory()
            try:
                run_watchlist_once(session, portfolio, watchlist)
            finally:
                session.close()
        elif was_market_hours:
            # Just crossed the square-off boundary -- flatten everything.
            session = session_factory()
            try:
                square_off_all_positions(session, portfolio)
            finally:
                session.close()
        was_market_hours = now_market_hours
        await asyncio.sleep(interval_seconds)
