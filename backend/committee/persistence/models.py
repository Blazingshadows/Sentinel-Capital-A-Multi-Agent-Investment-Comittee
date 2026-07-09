"""SQLAlchemy ORM models backing the Audit Layer and Dynamic Trust Framework.

JSON-shaped columns store `.model_dump_json()` of the corresponding pydantic
model from `backend.committee.schemas` — the ORM layer doesn't interpret
those payloads, it just persists and returns them so the audit trail is
always one query away from the exact objects the pipeline produced.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AgentPrediction(Base):
    """One row per agent per cycle per stock. `outcome_direction`/`correct`
    are filled in retroactively once the next cycle's price move is known —
    this table is the source of `historical_reliability` for the Dynamic
    Trust Framework."""

    __tablename__ = "agent_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    stock: Mapped[str] = mapped_column(String, nullable=False)
    agent: Mapped[str] = mapped_column(String, nullable=False)
    direction: Mapped[int] = mapped_column(Integer, nullable=False)  # -1 / 0 / 1
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    price_at_prediction: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_direction: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correct: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0/1


class Decision(Base):
    """One row per cycle per stock evaluated, whether or not a trade
    happened — satisfies README's "Per Trade Output" / explainability
    requirement end to end."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    stock: Mapped[str] = mapped_column(String, nullable=False)

    agent_recommendations: Mapped[str] = mapped_column(JSON, nullable=False)  # list[AgentOutput]
    debate: Mapped[str] = mapped_column(JSON, nullable=False)  # DebateResult
    influence_breakdown: Mapped[str] = mapped_column(JSON, nullable=False)  # list[AgentInfluence]

    consensus_decision: Mapped[str] = mapped_column(String, nullable=False)
    consensus_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    consensus_allocation: Mapped[float] = mapped_column(Float, nullable=False)
    consensus_reasoning: Mapped[str] = mapped_column(String, nullable=False)

    risk_action: Mapped[str] = mapped_column(String, nullable=False)
    risk_approved_allocation: Mapped[float] = mapped_column(Float, nullable=False)
    risk_volatility_estimate: Mapped[float] = mapped_column(Float, nullable=False)
    risk_reason: Mapped[str] = mapped_column(String, nullable=False)
    risk_expected_return: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    risk_expected_drawdown: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    alternatives: Mapped[str | None] = mapped_column(JSON, nullable=True)  # list[AlternativeCandidate]

    action_taken: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_breakdown: Mapped[str | None] = mapped_column(JSON, nullable=True)
    net_cash_flow: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    trades: Mapped[list["Trade"]] = relationship(back_populates="decision")


class Trade(Base):
    """One row per executed order (BUY/SELL). References the decision that
    triggered it, so the full reasoning trail is always one join away."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    stock: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    cost_breakdown: Mapped[str | None] = mapped_column(JSON, nullable=True)
    net_cash_flow: Mapped[float] = mapped_column(Float, nullable=False)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id"), nullable=True)

    decision: Mapped[Decision | None] = relationship(back_populates="trades")


class PortfolioSnapshotRow(Base):
    """Periodic portfolio marks — the dashboard's portfolio curve and
    session-end Sharpe/max-drawdown are computed from this table."""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    positions: Mapped[str] = mapped_column(JSON, nullable=False)  # {symbol: qty}
    portfolio_value: Mapped[float] = mapped_column(Float, nullable=False)
    net_pnl: Mapped[float] = mapped_column(Float, nullable=False)


class TrustScore(Base):
    """One row per agent — the Dynamic Trust Framework's persisted state.
    `total_predictions`/`correct_predictions` drive the Laplace-smoothed
    historical-reliability estimate consumed by the Consensus Orchestrator."""

    __tablename__ = "trust_scores"

    agent: Mapped[str] = mapped_column(String, primary_key=True)
    trust_score: Mapped[float] = mapped_column(Float, nullable=False)
    total_predictions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_predictions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
