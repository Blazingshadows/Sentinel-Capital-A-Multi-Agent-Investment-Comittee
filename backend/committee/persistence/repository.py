"""Read/write helpers over the ORM models, working in terms of the pydantic
schemas everything else in the committee already speaks. Callers never
construct a `models.*` row by hand.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.committee.config import TRUST_PRIOR
from backend.committee.persistence import models
from backend.committee.schemas import (
    AgentInfluence,
    AgentOutput,
    ConsensusDecision,
    DebateResult,
    Decision as DecisionEnum,
    DecisionLog,
    PortfolioSnapshot,
    RiskVerdict,
    TradeRecord,
)


def insert_decision_log(session: Session, log: DecisionLog) -> int:
    row = models.Decision(
        cycle_ts=log.cycle_ts,
        stock=log.stock,
        agent_recommendations=[a.model_dump(mode="json") for a in log.consensus.debate.revised_recommendations],
        debate=log.consensus.debate.model_dump(mode="json"),
        influence_breakdown=[a.model_dump(mode="json") for a in log.consensus.influence_breakdown],
        consensus_decision=log.consensus.decision.value,
        consensus_confidence=log.consensus.confidence,
        consensus_allocation=log.consensus.allocation,
        consensus_reasoning=log.consensus.reasoning,
        risk_action=log.risk_verdict.action.value,
        risk_approved_allocation=log.risk_verdict.approved_allocation,
        risk_volatility_estimate=log.risk_verdict.volatility_estimate,
        risk_reason=log.risk_verdict.reason,
        action_taken=log.trade.action.value,
        qty=log.trade.qty,
        price=log.trade.price,
        cost_breakdown=log.trade.cost_breakdown.model_dump(mode="json") if log.trade.cost_breakdown else None,
        net_cash_flow=log.trade.net_cash_flow,
    )
    session.add(row)
    session.flush()

    if log.trade.qty > 0:
        session.add(
            models.Trade(
                ts=log.cycle_ts,
                stock=log.stock,
                action=log.trade.action.value,
                qty=log.trade.qty,
                price=log.trade.price,
                cost_breakdown=log.trade.cost_breakdown.model_dump(mode="json") if log.trade.cost_breakdown else None,
                net_cash_flow=log.trade.net_cash_flow,
                decision_id=row.id,
            )
        )

    session.commit()
    return row.id


def record_agent_predictions(session: Session, cycle_ts: datetime, stock: str, outputs: list[AgentOutput]) -> None:
    for output in outputs:
        session.add(
            models.AgentPrediction(
                cycle_ts=cycle_ts,
                stock=stock,
                agent=output.agent,
                direction={DecisionEnum.BUY: 1, DecisionEnum.SELL: -1, DecisionEnum.WAIT: 0}[output.decision],
                confidence=output.confidence,
            )
        )
    session.commit()


def backfill_prediction_outcomes(session: Session, stock: str, before: datetime, actual_direction: int) -> None:
    """Called at the start of the next cycle for `stock`: resolves every
    still-open prediction against the price move that actually happened, so
    the Dynamic Trust Framework has fresh accuracy data to work with."""

    open_predictions = (
        session.query(models.AgentPrediction)
        .filter(
            models.AgentPrediction.stock == stock,
            models.AgentPrediction.cycle_ts < before,
            models.AgentPrediction.outcome_direction.is_(None),
        )
        .all()
    )
    for prediction in open_predictions:
        prediction.outcome_direction = actual_direction
        prediction.correct = int(prediction.direction == actual_direction)
    session.commit()


def get_trust_score(session: Session, agent: str) -> float:
    row = session.get(models.TrustScore, agent)
    return row.trust_score if row else TRUST_PRIOR


def update_trust_score(session: Session, agent: str) -> float:
    """Laplace-smoothed hit-rate over every resolved prediction this agent
    has made, so a cold-start agent starts near `TRUST_PRIOR` rather than 0
    or 1 after a single lucky/unlucky call."""

    resolved = (
        session.query(models.AgentPrediction)
        .filter(models.AgentPrediction.agent == agent, models.AgentPrediction.correct.is_not(None))
        .all()
    )
    correct = sum(p.correct for p in resolved)
    total = len(resolved)
    smoothed = (correct + TRUST_PRIOR * 2) / (total + 2)

    row = session.get(models.TrustScore, agent)
    if row is None:
        row = models.TrustScore(agent=agent, trust_score=smoothed, total_predictions=total,
                                 correct_predictions=correct, updated_at=datetime.now(timezone.utc))
        session.add(row)
    else:
        row.trust_score = smoothed
        row.total_predictions = total
        row.correct_predictions = correct
        row.updated_at = datetime.now(timezone.utc)
    session.commit()
    return smoothed


def insert_portfolio_snapshot(session: Session, snapshot: PortfolioSnapshot) -> None:
    session.add(
        models.PortfolioSnapshotRow(
            ts=snapshot.ts,
            cash=snapshot.cash,
            positions=snapshot.positions,
            portfolio_value=snapshot.portfolio_value,
            net_pnl=snapshot.net_pnl,
        )
    )
    session.commit()


def get_trade_history(session: Session, stock: str | None = None) -> list[models.Trade]:
    query = session.query(models.Trade)
    if stock:
        query = query.filter(models.Trade.stock == stock)
    return query.order_by(models.Trade.ts).all()


def get_portfolio_curve(session: Session) -> list[models.PortfolioSnapshotRow]:
    return session.query(models.PortfolioSnapshotRow).order_by(models.PortfolioSnapshotRow.ts).all()


def get_decision_log(session: Session, stock: str | None = None) -> list[models.Decision]:
    query = session.query(models.Decision)
    if stock:
        query = query.filter(models.Decision.stock == stock)
    return query.order_by(models.Decision.cycle_ts).all()
