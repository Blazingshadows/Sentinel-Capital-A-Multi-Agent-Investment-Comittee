"""Shared data contracts for every layer described in README.md.

Every specialist agent produces an `AgentOutput`. The Debate Layer turns a
list of them into a `DebateResult`. The Consensus Orchestrator turns that
into a `ConsensusDecision`. The Risk Management Layer turns that into a
`RiskVerdict`. The Execution Layer turns an approved verdict into a
`TradeRecord`. Nothing downstream needs to know how an upstream layer
computed its output — only this shape.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, computed_field


class Decision(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"


class RiskAction(str, Enum):
    APPROVE = "APPROVE"
    REDUCE = "REDUCE"
    REJECT = "REJECT"


class AgentOutput(BaseModel):
    """What every specialist agent (Technical, News & Sentiment, Macro,
    Contrarian) returns each cycle."""

    agent: str
    decision: Decision
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    evidence: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def signed_vote(self) -> float:
        sign = {Decision.BUY: 1, Decision.SELL: -1, Decision.WAIT: 0}[self.decision]
        return sign * self.confidence


class DebateResult(BaseModel):
    """Output of the Debate Layer (README §3): independent recommendations,
    the Contrarian's challenge, and the revised recommendations agents
    settled on after seeing it."""

    original_recommendations: list[AgentOutput]
    contrarian_challenge: str
    contrarian_risk_observations: list[str] = Field(default_factory=list)
    revised_recommendations: list[AgentOutput]


class AgentInfluence(BaseModel):
    """Every factor behind one agent's weight this cycle — the Dynamic Trust
    Framework's `Agent Influence = Confidence x Trust x Context Relevance`,
    logged so the committee stays explainable rather than a black box."""

    agent: str
    confidence: float
    trust_score: float
    context_relevance: float
    influence_raw: float
    influence_normalized: float
    signed_vote: float


class ConsensusDecision(BaseModel):
    """Output of the Consensus Orchestrator for one stock, one cycle. Matches
    README's worked example: `{symbol, allocation, confidence, decision}`."""

    symbol: str
    decision: Decision
    confidence: float = Field(ge=0.0, le=1.0)
    allocation: float = Field(ge=0.0, le=2.0, description="Fraction of base capital; up to 2.0 under 1:2 leverage")
    reasoning: str
    influence_breakdown: list[AgentInfluence]
    debate: DebateResult


class RiskVerdict(BaseModel):
    """Output of the Risk Management Layer — final approval authority before
    any capital is deployed."""

    action: RiskAction
    approved_allocation: float = Field(ge=0.0, le=2.0)
    volatility_estimate: float = Field(ge=0.0, description="GARCH-estimated annualized volatility")
    reason: str


class CostBreakdown(BaseModel):
    """Every NSE intraday cost component, applied on every simulated fill."""

    brokerage: float = Field(ge=0.0)
    stt: float = Field(ge=0.0)
    exchange_txn_charges: float = Field(ge=0.0)
    sebi_charges: float = Field(ge=0.0)
    stamp_duty: float = Field(ge=0.0)
    gst: float = Field(ge=0.0)
    slippage: float = Field(ge=0.0)

    @computed_field
    @property
    def total_cost(self) -> float:
        return (
            self.brokerage
            + self.stt
            + self.exchange_txn_charges
            + self.sebi_charges
            + self.stamp_duty
            + self.gst
            + self.slippage
        )


class TradeRecord(BaseModel):
    """Output of the Execution Layer for one executed (or skipped) order."""

    symbol: str
    action: Decision
    qty: float = 0.0
    price: float = 0.0
    cost_breakdown: CostBreakdown | None = None
    net_cash_flow: float = 0.0


class PortfolioSnapshot(BaseModel):
    ts: datetime
    cash: float
    positions: dict[str, float]
    portfolio_value: float
    net_pnl: float


class DecisionLog(BaseModel):
    """One full audit row per cycle per stock — everything needed to
    reconstruct why the committee acted (or didn't), from raw agent votes
    through to the executed trade. This is the Audit Layer's persisted unit."""

    cycle_ts: datetime
    stock: str
    consensus: ConsensusDecision
    risk_verdict: RiskVerdict
    trade: TradeRecord
