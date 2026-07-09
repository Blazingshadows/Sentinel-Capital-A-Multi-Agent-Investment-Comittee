"""Read/write helpers over the ORM models, working in terms of the pydantic
schemas everything else in the committee already speaks. Callers never
construct a `models.*` row by hand.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.committee.config import FORECAST_DEADZONE_MIN_RETURN, FORECAST_LOOKAHEAD_BARS, TRUST_PRIOR
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


_DIRECTION_BY_DECISION = {
    DecisionEnum.BUY: 1,
    DecisionEnum.SELL: -1,
    DecisionEnum.WAIT: 0,
    DecisionEnum.HOLD: 0,
    DecisionEnum.SWITCH: 0,
}

# Predictions are resolved against the price move over roughly this many
# bars, not the very next one -- see backfill_prediction_outcomes.
_PREDICTION_RESOLUTION_HORIZON = timedelta(minutes=5 * FORECAST_LOOKAHEAD_BARS)


def record_agent_predictions(
    session: Session, cycle_ts: datetime, stock: str, outputs: list[AgentOutput], price: float
) -> None:
    for output in outputs:
        session.add(
            models.AgentPrediction(
                cycle_ts=cycle_ts,
                stock=stock,
                agent=output.agent,
                direction=_DIRECTION_BY_DECISION[output.decision],
                confidence=output.confidence,
                price_at_prediction=price,
            )
        )
    session.commit()


def backfill_prediction_outcomes(session: Session, stock: str, before: datetime, current_price: float) -> None:
    """Resolves predictions against the price move over roughly their own
    intended horizon (`FORECAST_LOOKAHEAD_BARS` x 5-minute bars, the
    project-wide bar size) instead of the very next bar's raw sign.

    Previously this resolved *every* open prediction on the very next cycle
    against a single next-bar up/down/flat read -- noise-dominated (a single
    5-minute bar is close to a coin flip for a large-cap) and horizon-
    mismatched for the Forecasting agent specifically, whose own training
    label targets a `FORECAST_LOOKAHEAD_BARS`-bar move, not a 1-bar one. A
    prediction now only resolves once that much wall-clock time has actually
    elapsed since it was made, compared directly against the price at
    prediction time -- the same volatility-scaled-deadzone philosophy
    Forecasting's own labels use (a flat deadzone here, not volatility-
    scaled, is the deliberate simplification: no rolling-vol series is
    available at resolution time without re-fetching history).
    """
    cutoff = before - _PREDICTION_RESOLUTION_HORIZON
    ready = (
        session.query(models.AgentPrediction)
        .filter(
            models.AgentPrediction.stock == stock,
            models.AgentPrediction.cycle_ts <= cutoff,
            models.AgentPrediction.outcome_direction.is_(None),
            models.AgentPrediction.price_at_prediction.is_not(None),
        )
        .all()
    )
    for prediction in ready:
        forward_return = (current_price - prediction.price_at_prediction) / prediction.price_at_prediction
        if forward_return > FORECAST_DEADZONE_MIN_RETURN:
            actual_direction = 1
        elif forward_return < -FORECAST_DEADZONE_MIN_RETURN:
            actual_direction = -1
        else:
            actual_direction = 0
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
