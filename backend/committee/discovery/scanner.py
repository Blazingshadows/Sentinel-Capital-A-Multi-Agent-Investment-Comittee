"""Market Scanner Agent — Stage 1 of Opportunity Discovery.

Reduces the raw universe to *tradeable survivors*, each with a per-symbol
metric bundle, and labels the market regime + cross-sectional dispersion.
High-recall by contract: it only removes obviously-untradeable names (no
history, illiquid, penny price, degenerate data). Every metric is computed
once here and reused downstream (DRY). No directional opinion, no forecast.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from backend.committee.discovery import indicators
from backend.committee.discovery.interfaces import AbstractMarketScanner, ConfigAware
from backend.committee.discovery.schemas import (
    MarketRegime,
    RejectReason,
    ScanReport,
    SymbolScan,
)

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


class MarketScannerAgent(ConfigAware, AbstractMarketScanner):
    """High-recall pre-screen. Config injected via `ConfigAware`."""

    def scan(
        self, ohlcv_by_symbol: dict[str, pd.DataFrame], sector_by_symbol: dict[str, str | None]
    ) -> tuple[list[SymbolScan], ScanReport]:
        universe_size = len(ohlcv_by_symbol)
        scans = [self._scan_one(sym, df, sector_by_symbol.get(sym)) for sym, df in ohlcv_by_symbol.items()]
        passed = [s for s in scans if s.passed]

        reject_breakdown: dict[str, int] = {}
        for s in scans:
            if not s.passed and s.reject_reason is not None:
                reject_breakdown[s.reject_reason.value] = reject_breakdown.get(s.reject_reason.value, 0) + 1

        report = ScanReport(
            universe_size=universe_size,
            scanned=len(scans),
            passed=len(passed),
            rejected=len(scans) - len(passed),
            reject_breakdown=reject_breakdown,
            regime=self._detect_regime(passed),
            coverage_pct=round(len(scans) / universe_size, 4) if universe_size else 0.0,
            cross_sectional_dispersion=self._dispersion(passed),
        )
        logger.info(
            "Scan: %d/%d passed (regime=%s, dispersion=%.4f, rejects=%s)",
            len(passed), len(scans), report.regime.value, report.cross_sectional_dispersion, reject_breakdown,
        )
        return scans, report

    # -- per-symbol -----------------------------------------------------------

    def _scan_one(self, symbol: str, ohlcv: pd.DataFrame, sector: str | None) -> SymbolScan:
        cfg = self.config.scanner

        if ohlcv is None or ohlcv.empty or not set(_REQUIRED_COLUMNS).issubset(ohlcv.columns):
            return self._reject(symbol, sector, RejectReason.STALE_OR_MISSING_DATA)

        ohlcv = ohlcv.dropna(subset=list(_REQUIRED_COLUMNS))
        bars = len(ohlcv)
        if bars < cfg.min_bars:
            return self._reject(symbol, sector, RejectReason.INSUFFICIENT_HISTORY, bars=bars)

        close, volume = ohlcv["Close"], ohlcv["Volume"]
        last_price = float(close.iloc[-1])
        if last_price < cfg.min_last_price:
            return self._reject(symbol, sector, RejectReason.UNTRADEABLE_PRICE, bars=bars, last_price=last_price)
        if float(close.std()) == 0.0 or float(volume.sum()) == 0.0:
            return self._reject(symbol, sector, RejectReason.DEGENERATE_SERIES, bars=bars, last_price=last_price)

        median_turnover = float((close * volume).median())
        if not np.isfinite(median_turnover) or median_turnover < cfg.min_median_turnover:
            return self._reject(
                symbol, sector, RejectReason.ILLIQUID, bars=bars, last_price=last_price,
                median_turnover=median_turnover if np.isfinite(median_turnover) else 0.0,
            )

        bars_per_year = cfg.bars_per_day * cfg.trend_days_per_year
        atr_pct = indicators.atr_percent(ohlcv, cfg.atr_period)
        hist_vol = indicators.realized_volatility(close, cfg.hist_vol_window, bars_per_year)
        adx = _last_finite(indicators.average_directional_index(ohlcv, cfg.adx_period))
        rel_vol = indicators.relative_volume(volume, cfg.rel_volume_window, cfg.rel_volume_recent_window)
        momentum = indicators.blended_momentum(close, cfg.momentum_lookbacks)
        ra_momentum = indicators.risk_adjusted_momentum(close, cfg.momentum_lookbacks, cfg.hist_vol_window)
        efficiency = indicators.efficiency_ratio(close, cfg.efficiency_window)
        slope = indicators.trend_slope(close, cfg.ema_fast, cfg.ema_slow)
        gap = indicators.gap_pct(ohlcv)
        vol_exp = indicators.vol_expansion_ratio(close, cfg.vol_expansion_short, cfg.vol_expansion_long)
        stretch = indicators.ema_stretch_atr(ohlcv, cfg.ema_stretch_span, cfg.atr_period)
        rng_pos = indicators.range_position(close, cfg.range_window)

        completeness = _completeness([atr_pct, hist_vol, adx, rel_vol, ra_momentum, efficiency, vol_exp, stretch])

        return SymbolScan(
            symbol=symbol, passed=True, sector=sector,
            last_price=last_price, median_turnover=median_turnover,
            atr_pct=atr_pct, hist_volatility=hist_vol, adx=adx, relative_volume=rel_vol,
            momentum=momentum, risk_adj_momentum=ra_momentum, trend_efficiency=efficiency,
            trend_slope=slope, gap_pct=gap, vol_expansion_ratio=vol_exp,
            ema_stretch=stretch, range_position=rng_pos,
            bars_available=bars, data_completeness=completeness,
        )

    def _reject(self, symbol, sector, reason, *, bars=0, last_price=0.0, median_turnover=0.0) -> SymbolScan:
        return SymbolScan(
            symbol=symbol, passed=False, reject_reason=reason, sector=sector,
            last_price=last_price, median_turnover=median_turnover,
            bars_available=bars, data_completeness=0.0,
        )

    # -- cross-sectional ------------------------------------------------------

    def _detect_regime(self, passed: list[SymbolScan]) -> MarketRegime:
        cfg = self.config.scanner
        if not passed:
            return MarketRegime.UNKNOWN
        breadth = float(np.mean([1.0 if s.trend_slope > 0 else 0.0 for s in passed]))
        median_atr = float(np.median([s.atr_pct for s in passed]))
        if median_atr >= cfg.regime_high_vol_atr_pct:
            return MarketRegime.HIGH_VOLATILITY
        if breadth >= cfg.regime_risk_on_breadth:
            return MarketRegime.RISK_ON
        if breadth <= cfg.regime_risk_off_breadth:
            return MarketRegime.RISK_OFF
        return MarketRegime.NEUTRAL

    def _dispersion(self, passed: list[SymbolScan]) -> float:
        """MAD of survivor risk-adjusted momentum — how much cross-sectional
        spread there is to pick from (high = stock-picking-rich, low =
        macro-driven). Feeds selection-width monitoring."""
        if not passed:
            return 0.0
        values = np.array([s.risk_adj_momentum for s in passed])
        return float(np.median(np.abs(values - np.median(values))))


def _last_finite(series: pd.Series) -> float:
    clean = series.dropna()
    if clean.empty:
        return 0.0
    value = float(clean.iloc[-1])
    return value if np.isfinite(value) else 0.0


def _completeness(values: list[float]) -> float:
    finite = sum(1 for v in values if np.isfinite(v))
    return finite / len(values) if values else 0.0
