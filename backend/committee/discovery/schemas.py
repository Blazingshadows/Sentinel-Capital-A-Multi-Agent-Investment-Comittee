"""Data contracts for the Opportunity Discovery subsystem.

Pydantic v2 models (matching `backend/committee/schemas.py`), with
`.model_dump(mode="json")` producing the machine-readable audit payload. Every
selected stock carries its full factor breakdown, contributions, reasoning,
confidence decomposition and selection explanation, so the output is
explainable end to end. Pure contracts — no pandas/IO dependency.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MarketRegime(str, Enum):
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    NEUTRAL = "NEUTRAL"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    UNKNOWN = "UNKNOWN"


class RejectReason(str, Enum):
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    ILLIQUID = "ILLIQUID"
    UNTRADEABLE_PRICE = "UNTRADEABLE_PRICE"
    STALE_OR_MISSING_DATA = "STALE_OR_MISSING_DATA"
    DEGENERATE_SERIES = "DEGENERATE_SERIES"


class SymbolScan(BaseModel):
    """Market Scanner's per-symbol measurement bundle — raw, un-scored metrics,
    computed once and reused by the Scoring stage (DRY)."""

    symbol: str
    passed: bool
    reject_reason: RejectReason | None = None
    sector: str | None = None

    last_price: float = 0.0
    median_turnover: float = 0.0  # median(close * volume), liquidity proxy in currency
    atr_pct: float = 0.0  # ATR / price (tradeable range; used for the risk gate)
    hist_volatility: float = 0.0  # annualized realized volatility
    adx: float = 0.0  # trend strength 0-100 (kept for explainability)
    relative_volume: float = 1.0  # recent-window mean volume / trailing median (seasonality-robust)
    momentum: float = 0.0  # blended multi-horizon return (signed, raw)
    risk_adj_momentum: float = 0.0  # information-ratio momentum: per-horizon return / expected vol (signed)
    trend_efficiency: float = 0.0  # Kaufman efficiency ratio |net move| / path length, [0,1]
    trend_slope: float = 0.0  # normalized EMA-fast-vs-slow spread (signed)
    gap_pct: float = 0.0  # latest bar open-vs-prev-close gap (signed)
    vol_expansion_ratio: float = 1.0  # short-window vol / long-window vol (>1 = waking up from a quiet base)
    ema_stretch: float = 0.0  # (close - EMA) / ATR, signed distance in ATR units (mean-reversion)
    range_position: float = 0.5  # (close - low_n) / (high_n - low_n) in [0,1] (breakout proximity)
    bars_available: int = 0
    data_completeness: float = 1.0  # fraction of required metrics that were computable


class FactorScores(BaseModel):
    """Independent, standardized factor scores for one symbol (already
    cross-sectionally normalized, weight-free). Field order defines the
    factor-matrix column order — the single source of truth for the factor
    set (see scoring.py)."""

    liquidity: float = 0.0
    trend_quality: float = 0.0
    relative_strength: float = 0.0
    momentum: float = 0.0
    mean_reversion: float = 0.0
    breakout: float = 0.0
    volume_expansion: float = 0.0
    volatility_opportunity: float = 0.0
    sector_strength: float = 0.0
    event: float = 0.0
    risk_penalty: float = 0.0  # non-negative magnitude, subtracted in the composite


class OpportunityCandidate(BaseModel):
    """One scored (and possibly selected) stock, fully explained."""

    symbol: str
    sector: str | None = None
    rank: int = 0
    opportunity_score: float  # composite percentile, higher = more opportunity
    confidence: float = Field(ge=0.0, le=1.0)
    capacity_score: float = Field(default=0.0, ge=0.0, le=1.0)  # deployable-size proxy (log turnover, normalized)
    theme: str = ""  # dominant factor group, e.g. "momentum" | "vol_expansion" | "breakout"
    factor_scores: FactorScores
    factor_contributions: dict[str, float] = Field(default_factory=dict)  # weight * factor, signed
    contribution_pct: dict[str, float] = Field(default_factory=dict)  # |contribution| share of total, %
    confidence_breakdown: dict[str, float] = Field(default_factory=dict)  # drivers of the confidence figure
    reasoning: list[str] = Field(default_factory=list)
    selection_explanation: str = ""
    selected: bool = False


class ScanReport(BaseModel):
    """Diagnostics for the scan stage (coverage, regime, rejection breakdown,
    cross-sectional dispersion — supports the failure-mode monitoring)."""

    universe_size: int
    scanned: int
    passed: int
    rejected: int
    reject_breakdown: dict[str, int] = Field(default_factory=dict)
    regime: MarketRegime = MarketRegime.UNKNOWN
    coverage_pct: float = 0.0
    cross_sectional_dispersion: float = 0.0  # MAD of survivor momentum — stock-picking richness


class DiscoveryResult(BaseModel):
    """Top-level, machine-readable output of one discovery run."""

    cycle_ts: datetime
    regime: MarketRegime
    universe_size: int
    scanned: int
    survived_scan: int
    selected_count: int
    runtime_ms: float
    config_fingerprint: str
    scan_report: ScanReport
    candidates: list[OpportunityCandidate]  # selected, rank-ordered
    dropped_sample: list[str] = Field(default_factory=list)  # for recall backfill/monitoring
    diagnostics: dict[str, float] = Field(default_factory=dict)

    @property
    def selected_symbols(self) -> list[str]:
        return [c.symbol for c in self.candidates]
