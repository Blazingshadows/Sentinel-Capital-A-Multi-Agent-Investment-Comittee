"""Signal library for the AlgoEngine: named, reusable technical/cross-
sectional features grouped by trading style, each a pure function of OHLCV
(plus, for cross-sectional signals, the watchlist panel). `SIGNAL_REGISTRY`
is the single source of truth `algo_engine.features.build_all_signals` reads
to build a feature matrix, and that `algo_engine.features.iter_feature_subsets`
groups by `style` to build the "pure style" candidate subsets.
"""

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from backend.committee.signals import cross_sectional, mean_reversion, tail_risk, trend, volatility, volume

SignalFn = Callable[..., pd.Series]


@dataclass(frozen=True)
class SignalSpec:
    name: str
    fn: SignalFn
    style: str
    params: dict = field(default_factory=dict)
    needs_panel: bool = False


SIGNAL_REGISTRY: dict[str, SignalSpec] = {}


def _register(name: str, fn: SignalFn, style: str, needs_panel: bool = False, **params) -> None:
    SIGNAL_REGISTRY[name] = SignalSpec(name=name, fn=fn, style=style, params=params, needs_panel=needs_panel)


# --- Trend / momentum (CTA-style) -------------------------------------------
_register("trend_ema_cross", trend.ema_cross, "trend", fast=20, slow=50)
_register("trend_donchian_breakout", trend.donchian_breakout, "trend", window=20)
_register("trend_slope", trend.trend_slope, "trend", window=20)

# --- Mean reversion (stat-arb-style) ----------------------------------------
_register("mr_rsi_deviation", mean_reversion.rsi_deviation, "mean_reversion", period=14)
_register("mr_zscore_price", mean_reversion.zscore_price, "mean_reversion", window=20)
_register("mr_bollinger_pctb", mean_reversion.bollinger_pctb, "mean_reversion", window=20, num_std=2.0)
_register("mr_short_reversal", mean_reversion.short_reversal, "mean_reversion", period=3)

# --- Volatility regime (vol-risk-premium-style) -----------------------------
_register("volat_realized_ratio", volatility.realized_vol_ratio, "volatility", short=5, long=20)
_register("volat_atr_normalized", volatility.atr_normalized, "volatility", period=14)
_register("volat_atr_expansion", volatility.atr_expansion, "volatility", short=5, long=20)

# --- Volume / order-flow proxy ----------------------------------------------
_register("volu_volume_zscore", volume.volume_zscore, "volume", window=20)
_register("volu_obv_slope", volume.obv_slope, "volume", window=10)
_register("volu_vwap_deviation", volume.vwap_deviation, "volume", window=20)

# --- Cross-sectional relative strength (rotation/quality-proxy style) ------
_register("xs_relative_strength", cross_sectional.relative_strength, "cross_sectional", needs_panel=True, window=20)
_register("xs_sector_momentum_rank", cross_sectional.sector_momentum_rank, "cross_sectional", needs_panel=True, window=20)

# --- Tail risk / exhaustion (contrarian-style) ------------------------------
_register("tail_drawdown_from_high", tail_risk.drawdown_from_high, "tail_risk", window=50)
_register("tail_exhaustion_flag", tail_risk.exhaustion_flag, "tail_risk", rsi_period=14, vol_window=20)
_register("tail_gap_fade", tail_risk.gap_fade, "tail_risk")

STYLES: tuple[str, ...] = tuple(sorted({spec.style for spec in SIGNAL_REGISTRY.values()}))
