"""Opportunity Scoring Agent — Stage 2 of Opportunity Discovery.

A configurable, cross-sectional multi-factor Opportunity Score, engineered for
a large book:

* **Robust standardization with soft-winsor** (median/MAD, tanh) — regime-
  relative and scale-free, and it *preserves tail ordering* instead of
  hard-clipping the biggest movers (which would tie the very names discovery
  exists to find).
* **Decorrelation weighting** — factors are down-weighted by how correlated
  they are with the rest of the panel *this cycle*, so the momentum family
  (momentum / relative-strength / trend / sector) stops being counted four
  times. This is the promised orthogonalization, done in a way that stays
  fully explainable (effective weights are reported).
* **Risk-adjusted, horizon-normalized momentum**; **vol-expansion** (not
  level); **mean-reversion** and **breakout** dimensions.
* **Percentile Opportunity Score** (robust to outliers, directly readable).
* **Jackknife stability confidence** + fixed **signed** agreement.

Emits no directional call and no forecast — only a relative "how informative
is this name to look at" score.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from backend.committee.discovery.interfaces import AbstractOpportunityScorer, ConfigAware
from backend.committee.discovery.schemas import (
    FactorScores,
    OpportunityCandidate,
    ScanReport,
    SymbolScan,
)
from backend.committee.discovery.utils import finite_float, percentile_rank, robust_standardize

logger = logging.getLogger(__name__)

_RISK_FACTOR = "risk_penalty"
# Single source of truth for the factor set (schema field order == matrix order).
_SCORE_FACTORS: tuple[str, ...] = tuple(f for f in FactorScores.model_fields if f != _RISK_FACTOR)
_CONTRIBUTION_EPSILON = 1e-9
_CONFIDENCE_FLOOR = 1e-3  # keeps the weighted geometric mean well-defined


class OpportunityScoringAgent(ConfigAware, AbstractOpportunityScorer):
    def score(self, scans: list[SymbolScan], report: ScanReport) -> list[OpportunityCandidate]:
        survivors = [s for s in scans if s.passed]
        if not survivors:
            return []

        raw = self._raw_factor_frame(survivors)
        standardized = self._standardize(raw)
        eff_weights = self._effective_weights(standardized)
        contributions = self._contributions(standardized, eff_weights)
        composite = contributions.sum(axis=1)

        opportunity_score = percentile_rank(composite)
        significance = composite.rank(pct=True)
        stability = self._jackknife_stability(composite, contributions)
        capacity = self._capacity_scores(survivors)

        candidates = [
            self._build_candidate(scan, standardized, contributions, opportunity_score,
                                   significance, stability, capacity)
            for scan in survivors
        ]
        candidates.sort(key=lambda c: c.opportunity_score, reverse=True)
        for rank, cand in enumerate(candidates, start=1):
            cand.rank = rank
        logger.info("Scored %d survivors (decorrelate=%s).", len(candidates), self.config.scoring.decorrelate)
        return candidates

    # -- raw factors ----------------------------------------------------------

    def _raw_factor_frame(self, survivors: list[SymbolScan]) -> pd.DataFrame:
        index = [s.symbol for s in survivors]
        sector_strength_map, universe_median = self._sector_strength(survivors)

        rows = {}
        for s in survivors:
            sector_str = sector_strength_map.get(s.sector or "_UNKNOWN", universe_median)
            rows[s.symbol] = {
                "liquidity": np.log1p(max(s.median_turnover, 0.0)),
                "trend_quality": s.trend_efficiency,  # efficiency ratio, not raw ADX
                "relative_strength": s.risk_adj_momentum - sector_str,
                "momentum": s.risk_adj_momentum,  # risk-adjusted, horizon-normalized
                "mean_reversion": s.ema_stretch,  # signed stretch; magnitude factor
                "breakout": 2.0 * s.range_position - 1.0,  # -1 (lows) .. +1 (highs); magnitude factor
                "volume_expansion": np.log1p(max(s.relative_volume, 0.0)),
                "volatility_opportunity": s.vol_expansion_ratio,  # expansion, not level
                "sector_strength": sector_str,
                "event": self._event_raw(s),
                _RISK_FACTOR: self._risk_raw(s),
            }
        return pd.DataFrame.from_dict(rows, orient="index").reindex(index)

    def _sector_strength(self, survivors: list[SymbolScan]) -> tuple[dict[str, float], float]:
        by_sector: dict[str, list[float]] = {}
        for s in survivors:
            by_sector.setdefault(s.sector or "_UNKNOWN", []).append(s.risk_adj_momentum)
        strength = {k: float(np.median(v)) for k, v in by_sector.items()}
        universe_median = float(np.median([s.risk_adj_momentum for s in survivors]))
        return strength, universe_median

    def _event_raw(self, s: SymbolScan) -> float:
        """Graded, vol-scaled market-structure surprise (participation, gap in
        ATR units, vol expansion). Vol-scaling the gap means the threshold
        means the same thing across calm and stormy regimes."""
        cfg = self.config.scoring
        score = 0.0
        if s.relative_volume >= cfg.event_rel_volume:
            score += 1.0
        if s.atr_pct > 0 and abs(s.gap_pct) >= cfg.event_gap_atr_mult * s.atr_pct:
            score += 1.0
        if s.vol_expansion_ratio >= cfg.event_vol_expansion:
            score += 1.0
        return score

    def _risk_raw(self, s: SymbolScan) -> float:
        cfg = self.config.scoring
        penalty = 0.0
        if s.hist_volatility > cfg.risk_extreme_vol:
            penalty += s.hist_volatility - cfg.risk_extreme_vol
        buffer = cfg.risk_min_turnover_floor * cfg.risk_liquidity_buffer_mult
        if buffer > 0 and s.median_turnover < buffer:
            penalty += max(0.0, (buffer - s.median_turnover) / buffer)
        return penalty

    # -- standardization & weighting -----------------------------------------

    def _standardize(self, raw: pd.DataFrame) -> pd.DataFrame:
        cfg = self.config.scoring
        return pd.DataFrame(
            {col: robust_standardize(raw[col], cfg.winsor_z, cfg.mad_epsilon, cfg.winsor_method)
             for col in raw.columns},
            index=raw.index,
        )

    def _effective_weights(self, standardized: pd.DataFrame) -> dict[str, float]:
        """Base weights, optionally decorrelated: divide each score factor's
        weight by its summed absolute correlation with the panel (self
        included), then renormalize so the total score-factor weight is
        unchanged. A factor redundant with others is trusted less; an
        orthogonal one keeps its full say. Risk keeps its base weight."""
        base = {f: float(self.config.scoring.weights.get(f, 0.0)) for f in _SCORE_FACTORS}
        base[_RISK_FACTOR] = float(self.config.scoring.weights.get(_RISK_FACTOR, 0.0))
        if not self.config.scoring.decorrelate:
            return base

        # DataFrame .copy() alone isn't enough on newer pandas (copy-on-write
        # can still hand back a read-only .values array) -- force an actual
        # independent numpy array via to_numpy(copy=True) before
        # fill_diagonal writes into it in place.
        corr = standardized[list(_SCORE_FACTORS)].corr().abs()
        corr_array = corr.to_numpy(copy=True)
        np.fill_diagonal(corr_array, 1.0)
        corr = pd.DataFrame(corr_array, index=corr.index, columns=corr.columns).fillna(0.0)
        redundancy = corr.sum(axis=1).clip(lower=1.0)

        adjusted = {f: base[f] / float(redundancy[f]) for f in _SCORE_FACTORS}
        base_total = sum(base[f] for f in _SCORE_FACTORS)
        adj_total = sum(adjusted.values()) or 1.0
        scale = base_total / adj_total
        eff = {f: adjusted[f] * scale for f in _SCORE_FACTORS}
        eff[_RISK_FACTOR] = base[_RISK_FACTOR]
        return eff

    def _contributions(self, standardized: pd.DataFrame, eff_weights: dict[str, float]) -> pd.DataFrame:
        cfg = self.config.scoring
        contrib = pd.DataFrame(index=standardized.index)
        for factor in _SCORE_FACTORS:
            z = standardized[factor]
            value = z.abs() if factor in cfg.magnitude_factors else z
            contrib[factor] = eff_weights[factor] * value
        contrib[_RISK_FACTOR] = -eff_weights[_RISK_FACTOR] * standardized[_RISK_FACTOR].clip(lower=0.0)
        return contrib

    def _jackknife_stability(self, composite: pd.Series, contributions: pd.DataFrame) -> pd.Series:
        """Leave-one-factor-out rank stability: for each factor, recompute the
        composite without it and check whether the name stays in the top-K.
        The fraction of folds it survives is a cheap robustness/confidence
        signal — a name that is top only because of one factor scores low."""
        k = min(self.config.jackknife_top_k, len(composite))
        if k <= 0 or len(composite) <= 1:
            return pd.Series(1.0, index=composite.index)
        survivals = pd.Series(0.0, index=composite.index)
        columns = list(contributions.columns)
        for col in columns:
            loo = composite - contributions[col]
            threshold = loo.nlargest(k).min()
            survivals += (loo >= threshold).astype(float)
        return survivals / len(columns)

    def _capacity_scores(self, survivors: list[SymbolScan]) -> pd.Series:
        """Deployable-size proxy in [0,1]: cross-sectional percentile of log
        turnover. For a large book, opportunity value is edge x capacity."""
        turnover = pd.Series(
            {s.symbol: np.log1p(max(s.median_turnover, 0.0)) for s in survivors}
        )
        return percentile_rank(turnover) / 100.0

    # -- candidate assembly ---------------------------------------------------

    def _build_candidate(
        self, scan, standardized, contributions, opportunity_score, significance, stability, capacity
    ) -> OpportunityCandidate:
        sym = scan.symbol
        factor_scores = FactorScores(
            **{name: finite_float(standardized.at[sym, name]) for name in FactorScores.model_fields}
        )
        contrib = {k: finite_float(contributions.at[sym, k]) for k in contributions.columns}
        contribution_pct = self._contribution_pct(contrib)
        confidence, breakdown = self._confidence(
            scan, finite_float(significance.at[sym]), standardized.loc[sym], finite_float(stability.at[sym])
        )
        return OpportunityCandidate(
            symbol=sym,
            sector=scan.sector,
            opportunity_score=finite_float(opportunity_score.at[sym]),
            confidence=confidence,
            capacity_score=finite_float(capacity.at[sym]),
            theme=self._theme(contrib),
            factor_scores=factor_scores,
            factor_contributions=contrib,
            contribution_pct=contribution_pct,
            confidence_breakdown=breakdown,
            reasoning=self._reasoning(scan, contrib, contribution_pct),
        )

    def _contribution_pct(self, contrib: dict[str, float]) -> dict[str, float]:
        total = sum(abs(v) for v in contrib.values()) or 1.0
        return {k: round(100.0 * abs(v) / total, 2) for k, v in contrib.items()}

    def _theme(self, contrib: dict[str, float]) -> str:
        groups = self.config.scoring.factor_groups
        by_group: dict[str, float] = {}
        for factor, value in contrib.items():
            if factor == _RISK_FACTOR:
                continue
            group = groups.get(factor, factor)
            by_group[group] = by_group.get(group, 0.0) + abs(value)
        return max(by_group, key=by_group.get) if by_group else ""

    def _confidence(self, scan, significance, signed_row, stability):
        cfg = self.config.scoring
        weights = {
            "completeness": cfg.confidence_completeness_weight,
            "significance": cfg.confidence_significance_weight,
            "agreement": cfg.confidence_agreement_weight,
            "stability": cfg.confidence_stability_weight,
        }
        components = {
            "completeness": scan.data_completeness,
            "significance": significance,
            "agreement": self._agreement(signed_row),
            "stability": stability,
        }
        w_total = sum(weights.values()) or 1.0
        log_sum = sum(weights[k] * np.log(np.clip(components[k], _CONFIDENCE_FLOOR, 1.0)) for k in weights)
        confidence = float(np.clip(np.exp(log_sum / w_total), 0.0, 1.0))
        breakdown = {k: round(float(v), 4) for k, v in components.items()}
        return confidence, breakdown

    def _agreement(self, signed_row: pd.Series) -> float:
        """Net directional consensus across factors, using *signed* evidence
        (fixes the old bug where |z| magnitude factors always read as
        'agreeing'). 1 = all factors point the same way, 0 = they cancel."""
        cfg = self.config.scoring
        num = 0.0
        den = 0.0
        for factor in _SCORE_FACTORS:
            w = float(cfg.weights.get(factor, 0.0))
            if w <= 0:
                continue
            evidence = float(signed_row[factor]) / cfg.winsor_z  # normalized to [-1, 1]
            num += w * evidence
            den += w
        return abs(num) / den if den else 0.0

    def _reasoning(self, scan, contrib, contribution_pct) -> list[str]:
        ranked = sorted(
            ((k, v) for k, v in contrib.items() if k != _RISK_FACTOR),
            key=lambda kv: abs(kv[1]), reverse=True,
        )
        reasons = [
            f"{name} {value:+.2f} ({contribution_pct.get(name, 0):.0f}% of score)"
            for name, value in ranked[:3]
            if abs(value) > _CONTRIBUTION_EPSILON
        ]
        if contrib.get(_RISK_FACTOR, 0.0) < 0:
            reasons.append(f"risk penalty {contrib[_RISK_FACTOR]:+.2f} (elevated vol / thin liquidity)")
        reasons.append(
            f"riskAdjMom={scan.risk_adj_momentum:+.2f}, efficiency={scan.trend_efficiency:.2f}, "
            f"volExpansion={scan.vol_expansion_ratio:.2f}, relVol={scan.relative_volume:.1f}, "
            f"stretch={scan.ema_stretch:+.1f}ATR"
        )
        return reasons
