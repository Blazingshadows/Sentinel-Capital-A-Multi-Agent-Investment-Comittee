"""Tests for the Diversity Optimizer: sector caps, shrunk-correlation cluster
caps, capacity-aware selection, and the recall top-up."""

from collections import Counter

import numpy as np
import pandas as pd

from backend.committee.discovery.config import load_config
from backend.committee.discovery.diversity import DiversityOptimizerAgent
from backend.committee.discovery.schemas import FactorScores, OpportunityCandidate


def _cand(symbol, score, sector, capacity=0.5) -> OpportunityCandidate:
    return OpportunityCandidate(
        symbol=symbol, sector=sector, opportunity_score=score, confidence=0.5,
        capacity_score=capacity, factor_scores=FactorScores(),
    )


def test_respects_sector_cap():
    cfg = load_config()
    cfg.diversity.target_min = 6; cfg.diversity.target_max = 6
    cfg.diversity.max_per_sector_fraction = 0.34  # cap = 2
    sectors = ["IT", "Bank", "Auto", "Pharma", "Energy"]
    candidates = [_cand(f"{s}{i}", 100 - (j * 3 + i), s) for j, s in enumerate(sectors) for i in range(4)]
    selected = DiversityOptimizerAgent(cfg).optimize(candidates, returns_by_symbol=None)
    assert len(selected) == 6
    assert max(Counter(c.sector for c in selected).values()) <= 2


def test_shrunk_correlation_cluster_cap():
    cfg = load_config()
    cfg.diversity.target_min = 3; cfg.diversity.target_max = 8
    cfg.diversity.max_per_correlation_cluster = 3
    rng = np.random.default_rng(0)
    shared = pd.Series(rng.normal(0, 0.01, 60))
    returns, candidates = {}, []
    for i in range(5):
        sym = f"CORR{i}"; returns[sym] = shared + rng.normal(0, 1e-6, 60)
        candidates.append(_cand(sym, 100 - i, f"S{i}"))
    for i in range(7):
        sym = f"IND{i}"; returns[sym] = pd.Series(rng.normal(0, 0.01, 60))
        candidates.append(_cand(sym, 50 - i, f"T{i}"))
    selected = DiversityOptimizerAgent(cfg).optimize(candidates, returns_by_symbol=returns)
    assert len([c for c in selected if c.symbol.startswith("CORR")]) <= 3


def test_capacity_tilt_prefers_deployable_names():
    """Equal score, different capacity -> with capacity_weight>0 the more
    deployable name ranks first."""
    cfg = load_config()
    cfg.diversity.target_min = 1; cfg.diversity.target_max = 2
    cfg.diversity.capacity_weight = 0.5
    low = _cand("LOWCAP", 90.0, "IT", capacity=0.1)
    high = _cand("HIGHCAP", 90.0, "Bank", capacity=0.9)
    selected = DiversityOptimizerAgent(cfg).optimize([low, high], returns_by_symbol=None)
    assert selected[0].symbol == "HIGHCAP"


def test_recall_topup_meets_minimum():
    cfg = load_config()
    cfg.diversity.target_min = 5; cfg.diversity.target_max = 5
    cfg.diversity.max_per_sector_fraction = 0.2  # cap = 1 per sector, only 2 sectors
    candidates = [_cand(f"A{i}", 100 - i, "IT") for i in range(4)] + [_cand(f"B{i}", 90 - i, "Bank") for i in range(4)]
    selected = DiversityOptimizerAgent(cfg).optimize(candidates, returns_by_symbol=None)
    assert len(selected) == 5


def test_selection_ranked_and_explained():
    cfg = load_config()
    cfg.diversity.target_min = 3; cfg.diversity.target_max = 5
    candidates = [_cand(f"X{i}", 100 - i, f"S{i % 4}") for i in range(20)]
    selected = DiversityOptimizerAgent(cfg).optimize(candidates)
    assert [c.rank for c in selected] == list(range(1, len(selected) + 1))
    assert all(c.selected and c.selection_explanation for c in selected)
    assert 3 <= len(selected) <= 5
