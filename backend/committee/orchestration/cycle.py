"""One full committee cycle for one stock: Market Data -> Specialist Agents
-> Debate -> Consensus -> Risk -> Execution -> Audit. Split into
`evaluate_context` (agents through risk, no capital committed yet) and
`finalize_cycle` (execute + persist) so a multi-symbol pass
(`orchestration.loop.run_watchlist_once`) can evaluate every watchlist
symbol first, run them all through the cross-symbol capital allocator, and
only then execute — a single symbol's risk verdict has no way to know what
capital other watchlist symbols want the same cycle. `process_context` is
the single-symbol convenience wrapper both live single-symbol cycles
(`run_cycle`) and Replay Mode (`backend.committee.replay.player`) run
through — Replay Mode is just an alternate way of producing a
`MarketContext`, never a separate code path.
"""

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy.orm import Session

from backend.committee.agents import forecasting, macro, news_sentiment, technical
from backend.committee.config import BASE_EXPERTISE
from backend.committee.consensus.orchestrator import run_consensus
from backend.committee.debate.engine import run_debate
from backend.committee.execution.portfolio import Portfolio, execute
from backend.committee.market_data.context import MarketContext, build_context
from backend.committee.persistence import repository
from backend.committee.risk import manager as risk_manager
from backend.committee.schemas import AgentOutput, ConsensusDecision, DecisionLog, RiskVerdict, TradeRecord
from backend.committee.trust.scoring import refresh_trust_scores


def _latest_bar_direction(ohlcv: pd.DataFrame) -> int:
    """Approximates "did the stock just go up or down" from the two most
    recent bars — the outcome signal used to resolve the previous cycle's
    open agent predictions for the Dynamic Trust Framework."""
    if len(ohlcv) < 2:
        return 0
    diff = ohlcv["Close"].iloc[-1] - ohlcv["Close"].iloc[-2]
    return 1 if diff > 0 else (-1 if diff < 0 else 0)


def evaluate_context(session: Session, context: MarketContext, cycle_ts: datetime) -> tuple[ConsensusDecision, RiskVerdict, list[AgentOutput]]:
    """Agents through Risk — no capital committed, no trade executed yet."""
    actual_direction = _latest_bar_direction(context.ohlcv)
    repository.backfill_prediction_outcomes(session, context.symbol, before=cycle_ts, actual_direction=actual_direction)
    refresh_trust_scores(session, list(BASE_EXPERTISE))

    original_recommendations = [
        technical.analyze(context),
        news_sentiment.analyze(context),
        macro.analyze(context),
        forecasting.analyze(context),
    ]

    debate = run_debate(context, original_recommendations)
    consensus = run_consensus(session, context.symbol, debate, context.context_flags)
    risk_verdict = risk_manager.evaluate(context, consensus)

    return consensus, risk_verdict, debate.revised_recommendations


def finalize_cycle(
    session: Session,
    portfolio: Portfolio,
    context: MarketContext,
    consensus: ConsensusDecision,
    risk_verdict: RiskVerdict,
    revised_recommendations: list[AgentOutput],
    cycle_ts: datetime,
) -> DecisionLog:
    """Executes against `risk_verdict` as given — callers that need
    cross-symbol capital constraints apply them to `risk_verdict` before
    calling this, via `orchestration.allocator.allocate_capital`."""
    trade: TradeRecord = execute(portfolio, consensus, risk_verdict, context.latest_price)

    repository.record_agent_predictions(session, cycle_ts, context.symbol, revised_recommendations)

    log = DecisionLog(cycle_ts=cycle_ts, stock=context.symbol, consensus=consensus, risk_verdict=risk_verdict, trade=trade)
    repository.insert_decision_log(session, log)

    return log


def process_context(session: Session, portfolio: Portfolio, context: MarketContext, cycle_ts: datetime | None = None) -> tuple[DecisionLog, float]:
    cycle_ts = cycle_ts or datetime.now(timezone.utc)
    consensus, risk_verdict, revised_recommendations = evaluate_context(session, context, cycle_ts)
    log = finalize_cycle(session, portfolio, context, consensus, risk_verdict, revised_recommendations, cycle_ts)
    return log, context.latest_price


def run_cycle(session: Session, portfolio: Portfolio, symbol: str, context_flags: list[str] | None = None) -> tuple[DecisionLog, float]:
    context = build_context(symbol, context_flags=context_flags)
    return process_context(session, portfolio, context)
