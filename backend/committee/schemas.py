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
    HOLD = "HOLD"
    WAIT = "WAIT"
    SWITCH = "SWITCH"


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
        # HOLD/SWITCH are consensus-level decisions (they need portfolio
        # position and cross-symbol context no individual specialist has) --
        # specialists only ever emit BUY/SELL/WAIT. Mapped to 0 here anyway
        # so this never KeyErrors if that assumption is ever violated.
        sign = {Decision.BUY: 1, Decision.SELL: -1, Decision.WAIT: 0, Decision.HOLD: 0, Decision.SWITCH: 0}[self.decision]
        return sign * self.confidence


class LLMAgentVerdict(BaseModel):
    """Raw shape an LLM-backed agent asks Gemini to fill in — no `agent`
    field (the caller already knows which agent it is) and no computed
    fields, so the generation schema sent to the model stays unambiguous."""

    decision: Decision
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    evidence: list[str] = Field(default_factory=list)

    def to_agent_output(self, agent: str) -> "AgentOutput":
        return AgentOutput(
            agent=agent,
            decision=self.decision,
            confidence=self.confidence,
            reasoning=self.reasoning,
            evidence=self.evidence,
        )


class ContrarianVerdict(BaseModel):
    """Raw shape the Contrarian agent asks Gemini for. It plays a dual role
    (README): it casts its own directional vote like any other specialist
    (`decision`/`confidence`/`reasoning`/`evidence`), *and* it produces the
    challenge/risk observations that drive the Debate Layer's confidence
    revision pass — one LLM call covers both."""

    decision: Decision
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    evidence: list[str] = Field(default_factory=list)
    challenge: str
    risk_observations: list[str] = Field(default_factory=list)

    def to_agent_output(self, agent: str = "Contrarian") -> "AgentOutput":
        return AgentOutput(
            agent=agent,
            decision=self.decision,
            confidence=self.confidence,
            reasoning=self.reasoning,
            evidence=self.evidence,
        )


class DebateResult(BaseModel):
    """Output of the Debate Layer (README §3): independent recommendations,
    the Contrarian's challenge, and the revised recommendations agents
    settled on after seeing it."""

    original_recommendations: list[AgentOutput]
    contrarian_challenge: str
    contrarian_risk_observations: list[str] = Field(default_factory=list)
    revised_recommendations: list[AgentOutput]


class AgentInfluence(BaseModel):
    """Every factor behind one agent's weight this cycle -- the Dynamic Trust
    Framework's `Agent Influence = Confidence x Trust x Expertise x Context
    Relevance x Agreement`, logged so the committee stays explainable rather
    than a black box. `trust_score` is historical reliability itself
    (Laplace-smoothed resolved-prediction hit rate); `agreement_factor` is
    this agent's this-cycle divergence from the rest of the committee,
    discounted when redundant and boosted when it's trust-backed dissent."""

    agent: str
    confidence: float
    trust_score: float
    expertise: float
    context_relevance: float
    agreement_factor: float
    influence_raw: float
    influence_normalized: float
    signed_vote: float


class AlternativeCandidate(BaseModel):
    """One other watchlist symbol's consensus this same cycle, surfaced so a
    decision can report the PS-mandated "Alternative Stocks Considered" --
    only meaningful in a watchlist pass, where every symbol is evaluated
    together; a single-symbol cycle has nothing to compare against."""

    symbol: str
    decision: Decision
    confidence: float


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
    alternatives: list[AlternativeCandidate] = Field(default_factory=list)


class RiskVerdict(BaseModel):
    """Output of the Risk Management Layer — final approval authority before
    any capital is deployed."""

    action: RiskAction
    approved_allocation: float = Field(ge=0.0, le=2.0)
    volatility_estimate: float = Field(ge=0.0, description="GARCH-estimated annualized volatility")
    reason: str
    expected_return: float = Field(
        default=0.0, description="Heuristic: signed, confidence x volatility scaled -- not a backtested figure"
    )
    expected_drawdown: float = Field(
        default=0.0, ge=0.0, description="Heuristic: volatility-scaled worst-case-this-trade estimate"
    )


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
