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


def run_specialists(
    session: Session, context: MarketContext, current_position: float = 0.0
) -> tuple[ConsensusDecision, RiskVerdict, list[AgentOutput]]:
    """Agents through Risk only — assumes this cycle's prediction-outcome
    backfill and trust-score refresh have already happened (see
    `evaluate_context`, or `orchestration.loop.run_watchlist_once`, which
    does both once for the whole watchlist rather than once per symbol
    before calling this directly). Split out from `evaluate_context` so a
    multi-symbol pass can run this — the expensive part, up to three
    different LLM providers' calls plus the local forecasting model — on a
    thread pool across symbols, while the DB backfill/refresh stays a single
    sequential step (redoing trust refresh per symbol was pure waste, and a
    write that isn't safe to run concurrently against one SQLite file).
    `current_position` (this symbol's existing qty, signed) is only used to
    let the Consensus layer distinguish HOLD from WAIT; it never reaches the
    specialist agents, which reason about the stock in isolation."""
    original_recommendations = [
        technical.analyze(context),
        news_sentiment.analyze(context),
        macro.analyze(context),
        forecasting.analyze(context),
    ]

    debate = run_debate(context, original_recommendations)
    consensus = run_consensus(session, context.symbol, debate, context.context_flags, current_position)
    risk_verdict = risk_manager.evaluate(context, consensus)

    return consensus, risk_verdict, debate.revised_recommendations


def evaluate_context(
    session: Session, context: MarketContext, cycle_ts: datetime, current_position: float = 0.0
) -> tuple[ConsensusDecision, RiskVerdict, list[AgentOutput]]:
    """Agents through Risk — no capital committed, no trade executed yet.
    Single-symbol convenience wrapper around `run_specialists` that also
    does this cycle's backfill/trust-refresh itself; watchlist passes do
    those once for every symbol instead (see `run_specialists`)."""
    repository.backfill_prediction_outcomes(session, context.symbol, before=cycle_ts, current_price=context.latest_price)
    refresh_trust_scores(session, list(BASE_EXPERTISE))
    return run_specialists(session, context, current_position)


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

    repository.record_agent_predictions(session, cycle_ts, context.symbol, revised_recommendations, context.latest_price)

    log = DecisionLog(cycle_ts=cycle_ts, stock=context.symbol, consensus=consensus, risk_verdict=risk_verdict, trade=trade)
    repository.insert_decision_log(session, log)

    return log


def process_context(session: Session, portfolio: Portfolio, context: MarketContext, cycle_ts: datetime | None = None) -> tuple[DecisionLog, float]:
    cycle_ts = cycle_ts or datetime.now(timezone.utc)
    current_position = portfolio.positions.get(context.symbol, 0.0)
    consensus, risk_verdict, revised_recommendations = evaluate_context(session, context, cycle_ts, current_position)
    log = finalize_cycle(session, portfolio, context, consensus, risk_verdict, revised_recommendations, cycle_ts)
    return log, context.latest_price


def run_cycle(session: Session, portfolio: Portfolio, symbol: str, context_flags: list[str] | None = None) -> tuple[DecisionLog, float]:
    context = build_context(symbol, context_flags=context_flags)
    return process_context(session, portfolio, context)
