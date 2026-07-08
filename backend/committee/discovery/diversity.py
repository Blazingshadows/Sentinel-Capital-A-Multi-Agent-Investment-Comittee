"""Diversity Optimizer Agent — Stage 3 of Opportunity Discovery.

De-duplicates the scored candidates down to the target count, preserving the
highest *independent* opportunity via:

* **Sector cap** — no sector exceeds `max_per_sector_fraction` of the list.
* **Correlation clustering on a shrunk covariance** — Ledoit-Wolf shrinkage
  makes the short-window correlation estimate usable (a raw 60-bar corr over
  ~150 names is badly rank-deficient and invents spurious clusters); at most
  `max_per_correlation_cluster` names survive per cluster.
* **Similarity penalty** — greedy, submodular-style marginal-value damping.
* **Capacity tilt** — for a large book, opportunity value is edge x deployable
  size, so the marginal value is scaled by a bounded function of each name's
  capacity score.

Greedy selection over a monotone submodular objective carries the classic
(1 - 1/e) guarantee. Emits no directional opinion.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from backend.committee.discovery.interfaces import AbstractDiversityOptimizer, ConfigAware
from backend.committee.discovery.schemas import OpportunityCandidate

logger = logging.getLogger(__name__)


class DiversityOptimizerAgent(ConfigAware, AbstractDiversityOptimizer):
    """Config injected via `ConfigAware`."""

    def optimize(
        self,
        candidates: list[OpportunityCandidate],
        returns_by_symbol: dict[str, pd.Series] | None = None,
    ) -> list[OpportunityCandidate]:
        cfg = self.config.diversity
        if not candidates:
            return []

        pool = sorted(candidates, key=lambda c: c.opportunity_score, reverse=True)[: cfg.prescreen_top_n]
        cluster_of = self._cluster(pool, returns_by_symbol)
        max_per_sector = max(1, int(round(cfg.max_per_sector_fraction * cfg.target_max)))

        selected: list[OpportunityCandidate] = []
        sector_counts: dict[str, int] = {}
        cluster_counts: dict[int, int] = {}
        remaining = list(pool)

        while remaining and len(selected) < cfg.target_max:
            best_idx, best_val = -1, -np.inf
            for i, cand in enumerate(remaining):
                sector = cand.sector or "_UNKNOWN"
                cluster = cluster_of.get(cand.symbol, -1)
                if sector_counts.get(sector, 0) >= max_per_sector:
                    continue
                if cluster >= 0 and cluster_counts.get(cluster, 0) >= cfg.max_per_correlation_cluster:
                    continue
                marginal = self._marginal_value(cand, selected, cluster_of)
                if marginal > best_val:
                    best_val, best_idx = marginal, i
            if best_idx < 0:
                break
            chosen = remaining.pop(best_idx)
            sector = chosen.sector or "_UNKNOWN"
            cluster = cluster_of.get(chosen.symbol, -1)
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            if cluster >= 0:
                cluster_counts[cluster] = cluster_counts.get(cluster, 0) + 1
            chosen.selected = True
            chosen.selection_explanation = (
                f"Selected #{len(selected) + 1}: score {chosen.opportunity_score:.1f}, "
                f"capacity {chosen.capacity_score:.2f}, sector '{sector}' "
                f"({sector_counts[sector]}/{max_per_sector} cap), "
                f"corr-cluster {cluster if cluster >= 0 else 'n/a'}, "
                f"diversity+capacity-adjusted value {best_val:.1f}."
            )
            selected.append(chosen)

        if len(selected) < cfg.target_min:
            selected = self._relax_fill(selected, remaining, cfg.target_min)

        for rank, cand in enumerate(selected, start=1):
            cand.rank = rank
        logger.info(
            "Diversity: %d candidates -> %d selected across %d sectors.",
            len(candidates), len(selected), len(sector_counts),
        )
        return selected

    # -- marginal value -------------------------------------------------------

    def _marginal_value(self, cand, selected, cluster_of) -> float:
        cfg = self.config.diversity
        penalty = cfg.similarity_penalty * self._peer_overlap(cand, selected, cluster_of)
        capacity_multiplier = 1.0 + cfg.capacity_weight * (2.0 * cand.capacity_score - 1.0)
        return cand.opportunity_score * (1.0 - penalty) * capacity_multiplier

    def _peer_overlap(self, cand, selected, cluster_of) -> float:
        if not selected:
            return 0.0
        cluster = cluster_of.get(cand.symbol, -1)
        if cluster < 0:
            return 0.0
        same = sum(1 for s in selected if cluster_of.get(s.symbol, -2) == cluster)
        return min(1.0, same / len(selected))

    # -- clustering -----------------------------------------------------------

    def _cluster(self, pool, returns_by_symbol) -> dict[str, int]:
        symbols = [c.symbol for c in pool]
        if not returns_by_symbol:
            return self._sector_clusters(pool)

        corr = self._correlation(symbols, returns_by_symbol)
        if corr is None:
            return self._sector_clusters(pool)

        try:
            from sklearn.cluster import AgglomerativeClustering

            distance = (1.0 - corr).clip(lower=0.0).values
            n = distance.shape[0]
            if n <= 1:
                return {corr.columns[0]: 0} if n == 1 else {}
            model = AgglomerativeClustering(
                n_clusters=None, metric="precomputed", linkage="average",
                distance_threshold=1.0 - self.config.diversity.correlation_threshold,
            )
            labels = model.fit_predict(distance)
            return {sym: int(lbl) for sym, lbl in zip(corr.columns, labels)}
        except Exception:
            logger.warning("Clustering fell back to threshold union-find.", exc_info=True)
            return self._threshold_clusters(corr, self.config.diversity.correlation_threshold)

    def _correlation(self, symbols, returns_by_symbol) -> pd.DataFrame | None:
        cols = {s: returns_by_symbol[s] for s in symbols if s in returns_by_symbol}
        if len(cols) < 2:
            return None
        lookback = self.config.data.correlation_lookback_bars
        frame = pd.DataFrame({s: r.tail(lookback).reset_index(drop=True) for s, r in cols.items()}).dropna(axis=1, how="all")
        frame = frame.dropna()
        if frame.shape[1] < 2 or frame.shape[0] < 3:
            return None
        if self.config.diversity.use_shrinkage:
            shrunk = self._shrunk_correlation(frame)
            if shrunk is not None:
                return shrunk
        return frame.corr().fillna(0.0)

    def _shrunk_correlation(self, frame: pd.DataFrame) -> pd.DataFrame | None:
        """Ledoit-Wolf shrunk covariance -> correlation. Far more stable than a
        raw sample correlation on a short window with many names."""
        try:
            from sklearn.covariance import LedoitWolf

            cov = LedoitWolf().fit(frame.values).covariance_
            d = np.sqrt(np.clip(np.diag(cov), 1e-18, None))
            corr = cov / np.outer(d, d)
            corr = np.clip(corr, -1.0, 1.0)
            return pd.DataFrame(corr, index=frame.columns, columns=frame.columns)
        except Exception:
            logger.warning("Ledoit-Wolf shrinkage failed; using sample correlation.", exc_info=True)
            return None

    def _threshold_clusters(self, corr: pd.DataFrame, threshold: float) -> dict[str, int]:
        symbols = list(corr.columns)
        parent = {s: s for s in symbols}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i, a in enumerate(symbols):
            for b in symbols[i + 1:]:
                if abs(float(corr.at[a, b])) >= threshold:
                    parent[find(a)] = find(b)
        roots = {s: find(s) for s in symbols}
        ids = {root: idx for idx, root in enumerate(sorted(set(roots.values())))}
        return {s: ids[roots[s]] for s in symbols}

    def _sector_clusters(self, pool) -> dict[str, int]:
        ids: dict[str, int] = {}
        out: dict[str, int] = {}
        for c in pool:
            key = c.sector or "_UNKNOWN"
            if key not in ids:
                ids[key] = len(ids)
            out[c.symbol] = ids[key]
        return out

    def _relax_fill(self, selected, remaining, target_min) -> list[OpportunityCandidate]:
        chosen = {c.symbol for c in selected}
        for cand in sorted(remaining, key=lambda c: c.opportunity_score, reverse=True):
            if len(selected) >= target_min:
                break
            if cand.symbol in chosen:
                continue
            cand.selected = True
            cand.selection_explanation = (
                f"Selected via recall top-up (score {cand.opportunity_score:.1f}) after diversity caps "
                "left the list below the minimum target."
            )
            selected.append(cand)
            chosen.add(cand.symbol)
        return selected
