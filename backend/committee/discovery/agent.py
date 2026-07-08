"""Opportunity Discovery Agent — orchestrates Scanner -> Scorer -> Optimizer
into one `discover(...)` call and assembles the explainable `DiscoveryResult`.

Depends only on the abstract ports (all collaborators injected via the
constructor). Holds no global state; does its own timing/logging/error
handling; never forecasts or emits trade signals.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from backend.committee.discovery.config import DiscoveryConfig
from backend.committee.discovery.interfaces import (
    AbstractDiversityOptimizer,
    AbstractMarketScanner,
    AbstractOpportunityScorer,
    MarketDataPort,
)
from backend.committee.discovery.schemas import DiscoveryResult
from backend.committee.discovery.universe import load_universe

logger = logging.getLogger(__name__)


class OpportunityDiscoveryAgent:
    def __init__(
        self,
        config: DiscoveryConfig,
        data_provider: MarketDataPort,
        scanner: AbstractMarketScanner,
        scorer: AbstractOpportunityScorer,
        optimizer: AbstractDiversityOptimizer,
    ) -> None:
        self._config = config
        self._data = data_provider
        self._scanner = scanner
        self._scorer = scorer
        self._optimizer = optimizer

    def discover(self, universe: list[str] | None = None) -> DiscoveryResult:
        """One full discovery cycle. Fault-tolerant: individual symbol failures
        are skipped, and the run always returns a valid result."""
        started = time.perf_counter()
        cycle_ts = datetime.now(timezone.utc)
        symbols = universe if universe is not None else load_universe(fetchable_only=self._config.data.fetchable_only)
        logger.info("Discovery starting over %d symbols.", len(symbols))

        ohlcv_by_symbol = self._data.get_many_ohlcv(symbols)
        sector_by_symbol = {s: self._safe_sector(s) for s in ohlcv_by_symbol}

        scans, report = self._scanner.scan(ohlcv_by_symbol, sector_by_symbol)
        candidates = self._scorer.score(scans, report)

        returns_by_symbol = self._returns(ohlcv_by_symbol, [c.symbol for c in candidates])
        selected = self._optimizer.optimize(candidates, returns_by_symbol)

        selected_symbols = {c.symbol for c in selected}
        dropped = [c.symbol for c in candidates if c.symbol not in selected_symbols]
        runtime_ms = (time.perf_counter() - started) * 1000.0

        result = DiscoveryResult(
            cycle_ts=cycle_ts,
            regime=report.regime,
            universe_size=len(symbols),
            scanned=report.scanned,
            survived_scan=report.passed,
            selected_count=len(selected),
            runtime_ms=round(runtime_ms, 2),
            config_fingerprint=self._config.fingerprint(),
            scan_report=report,
            candidates=selected,
            dropped_sample=dropped[: self._config.dropped_sample_size],
            diagnostics=self._diagnostics(report, candidates, selected),
        )
        logger.info(
            "Discovery done in %.0f ms: %d -> %d survivors -> %d selected (regime=%s).",
            runtime_ms, len(symbols), report.passed, len(selected), report.regime.value,
        )
        return result

    # -- helpers --------------------------------------------------------------

    def _safe_sector(self, symbol: str) -> str | None:
        try:
            return self._data.get_sector(symbol)
        except Exception:
            logger.debug("Sector lookup failed for %s.", symbol, exc_info=True)
            return None

    def _returns(self, ohlcv_by_symbol: dict[str, pd.DataFrame], symbols: list[str]) -> dict[str, pd.Series]:
        lookback = self._config.data.correlation_lookback_bars
        out: dict[str, pd.Series] = {}
        for sym in symbols:
            df = ohlcv_by_symbol.get(sym)
            if df is None or "Close" not in df or len(df) < 3:
                continue
            returns = df["Close"].pct_change().dropna().tail(lookback)
            if len(returns) >= 3:
                out[sym] = returns
        return out

    def _diagnostics(self, report, candidates, selected) -> dict[str, float]:
        scores = [c.opportunity_score for c in candidates]
        sectors = {c.sector or "_UNKNOWN" for c in selected}
        return {
            "score_dispersion": float(np.std(scores)) if scores else 0.0,
            "mean_confidence": float(np.mean([c.confidence for c in selected])) if selected else 0.0,
            "mean_capacity": float(np.mean([c.capacity_score for c in selected])) if selected else 0.0,
            "selected_sector_count": float(len(sectors)),
            "survivor_count": float(report.passed),
            "cross_sectional_dispersion": report.cross_sectional_dispersion,
        }
