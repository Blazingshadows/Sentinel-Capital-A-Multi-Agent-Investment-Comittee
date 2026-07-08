"""Configuration for the Opportunity Discovery subsystem.

Every threshold, weight and window lives here as a typed, validated Pydantic
field with a sane default — there are **no magic numbers** in the algorithm
modules. Overridable from a JSON (or YAML if pyyaml is present) file via
`load_config(path)`, deep-merged onto the defaults.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "default_config.json"


class DataConfig(BaseModel):
    period: str = "60d"
    interval: str = "5m"  # Breeze has no native 15m bucket; the project uses 5m
    min_bars: int = 60
    max_fetch_workers: int = 12
    correlation_lookback_bars: int = 60  # bars for the diversity correlation estimate (shrunk)
    fetchable_only: bool = True  # live runs only attempt symbols with a Breeze stock_code mapping


class ScannerConfig(BaseModel):
    atr_period: int = 14
    adx_period: int = 14
    hist_vol_window: int = 20
    rel_volume_window: int = 20
    rel_volume_recent_window: int = 3  # average the last N bars (not one live/partial bar) for robustness
    momentum_lookbacks: list[int] = Field(default_factory=lambda: [3, 5, 10, 20])
    ema_fast: int = 20
    ema_slow: int = 50
    ema_stretch_span: int = 20
    range_window: int = 20
    efficiency_window: int = 20
    vol_expansion_short: int = 5
    vol_expansion_long: int = 20
    bars_per_day: int = 75  # NSE 9:15-15:30 / 5-min bars; annualizes realized vol
    trend_days_per_year: int = 252

    # Hard reject gates (recall-first: only clearly-untradeable names).
    min_last_price: float = 5.0
    min_median_turnover: float = 2_000_000.0
    min_bars: int = 60

    # Regime detection.
    regime_risk_on_breadth: float = 0.60
    regime_risk_off_breadth: float = 0.40
    regime_high_vol_atr_pct: float = 0.035


class ScoringConfig(BaseModel):
    winsor_z: float = 3.0
    winsor_method: str = "tanh"  # "tanh" soft-winsor (preserves tail ordering) or "clip"
    mad_epsilon: float = 1e-9
    decorrelate: bool = True  # down-weight factors by their cross-sectional correlation each cycle

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "liquidity": 0.6,
            "trend_quality": 1.0,
            "relative_strength": 1.0,
            "momentum": 1.1,
            "mean_reversion": 0.7,
            "breakout": 0.8,
            "volume_expansion": 0.9,
            "volatility_opportunity": 0.8,
            "sector_strength": 0.5,
            "event": 0.9,
            "risk_penalty": 1.0,  # subtracted
        }
    )

    # Two-sided factors (contribution = |z|: a big move either way is opportunity).
    magnitude_factors: list[str] = Field(
        default_factory=lambda: ["momentum", "relative_strength", "mean_reversion", "breakout"]
    )

    # Which factor each theme groups under (for decorrelation reporting + tags).
    factor_groups: dict[str, str] = Field(
        default_factory=lambda: {
            "momentum": "momentum",
            "relative_strength": "momentum",
            "trend_quality": "momentum",
            "sector_strength": "momentum",
            "mean_reversion": "mean_reversion",
            "breakout": "breakout",
            "volume_expansion": "volume",
            "volatility_opportunity": "vol_expansion",
            "event": "event",
            "liquidity": "liquidity",
        }
    )

    # Event detection (vol-scaled where possible, not regime-invariant).
    event_rel_volume: float = 2.0
    event_gap_atr_mult: float = 1.5  # |gap| >= this many ATRs is a gap event (vol-scaled)
    event_vol_expansion: float = 1.5

    # Risk penalty shaping.
    risk_extreme_vol: float = 0.90
    risk_min_turnover_floor: float = 2_000_000.0
    risk_liquidity_buffer_mult: float = 2.0

    # Confidence blend weights (geometric mean; auto-normalized).
    confidence_completeness_weight: float = 0.25
    confidence_significance_weight: float = 0.30
    confidence_agreement_weight: float = 0.20
    confidence_stability_weight: float = 0.25


class DiversityConfig(BaseModel):
    target_min: int = 50
    target_max: int = 60
    max_per_sector_fraction: float = 0.30
    correlation_threshold: float = 0.80
    max_per_correlation_cluster: int = 3
    similarity_penalty: float = 0.25
    capacity_weight: float = 0.20  # tilt selection toward deployable (high-turnover) names for large AUM
    use_shrinkage: bool = True  # Ledoit-Wolf shrinkage on the returns correlation before clustering
    prescreen_top_n: int = 150


class DiscoveryConfig(BaseModel):
    data: DataConfig = Field(default_factory=DataConfig)
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    diversity: DiversityConfig = Field(default_factory=DiversityConfig)
    dropped_sample_size: int = 30
    jackknife_top_k: int = 60  # stay-in-top-K set for the jackknife stability confidence

    def fingerprint(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, default=str).encode()
        return hashlib.sha256(payload).hexdigest()[:12]


def _read_overrides(path: Path) -> dict:
    text = path.read_text()
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(f"{path} is YAML but pyyaml is not installed; use JSON.") from exc
        return yaml.safe_load(text) or {}
    return json.loads(text) if text.strip() else {}


def load_config(path: str | Path | None = None) -> DiscoveryConfig:
    config = DiscoveryConfig()
    resolved = Path(path) if path else DEFAULT_CONFIG_PATH
    if resolved.exists():
        overrides = _read_overrides(resolved)
        if overrides:
            config = DiscoveryConfig.model_validate(_deep_merge(config.model_dump(), overrides))
    return config


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out
