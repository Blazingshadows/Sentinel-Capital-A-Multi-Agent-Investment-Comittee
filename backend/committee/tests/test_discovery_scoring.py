"""Tests for the Opportunity Scorer: ranking/determinism/explainability plus
the quant upgrades — decorrelation weighting, signed-agreement confidence,
vol-scaled events, risk penalty."""

import numpy as np
import pandas as pd

from backend.committee.discovery.config import load_config
from backend.committee.discovery.scanner import MarketScannerAgent
from backend.committee.discovery.scoring import _SCORE_FACTORS, OpportunityScoringAgent
from backend.committee.discovery.schemas import SymbolScan
from backend.committee.tests.discovery_synth import make_universe


def _score(config, universe, sectors):
    scans, report = MarketScannerAgent(config).scan(universe, sectors)
    return OpportunityScoringAgent(config).score(scans, report)


def _scan(**overrides) -> SymbolScan:
    base = dict(symbol="X", passed=True, sector="IT", last_price=100.0, median_turnover=1e8)
    base.update(overrides)
    return SymbolScan(**base)


def test_scores_ranked_explained_and_bounded():
    cfg = load_config()
    ohlcv, sectors = make_universe(40)
    candidates = _score(cfg, ohlcv, sectors)
    assert candidates
    scores = [c.opportunity_score for c in candidates]
    assert scores == sorted(scores, reverse=True)
    assert [c.rank for c in candidates] == list(range(1, len(candidates) + 1))
    for c in candidates:
        assert 0.0 <= c.confidence <= 1.0
        assert 0.0 <= c.capacity_score <= 1.0
        assert c.theme and c.reasoning
        assert set(c.confidence_breakdown) == {"completeness", "significance", "agreement", "stability"}
        assert all(0.0 <= v <= 1.0 for v in c.confidence_breakdown.values())


def test_empty_survivors_returns_empty():
    from backend.committee.tests.discovery_synth import make_ohlcv

    ohlcv = {f"P{i}": make_ohlcv(base=1.0, seed=i) for i in range(5)}
    assert _score(load_config(), ohlcv, {k: None for k in ohlcv}) == []


def test_scoring_deterministic():
    cfg = load_config()
    ohlcv, sectors = make_universe(40)
    a = _score(cfg, ohlcv, sectors)
    b = _score(cfg, ohlcv, sectors)
    assert [c.symbol for c in a] == [c.symbol for c in b]
    assert [round(c.opportunity_score, 6) for c in a] == [round(c.opportunity_score, 6) for c in b]


def test_decorrelation_downweights_redundant_factors():
    """Two identical factors should each be trusted less than an orthogonal
    one, while the total score-factor weight is preserved."""
    cfg = load_config()
    scorer = OpportunityScoringAgent(cfg)
    n = 50
    rng = np.random.default_rng(0)
    base_signal = rng.normal(0, 1, n)
    std = pd.DataFrame(index=[f"s{i}" for i in range(n)])
    for f in _SCORE_FACTORS:
        std[f] = rng.normal(0, 1, n)
    std["momentum"] = base_signal
    std["relative_strength"] = base_signal  # perfectly redundant with momentum
    std["risk_penalty"] = 0.0

    eff = scorer._effective_weights(std)
    base = cfg.scoring.weights
    assert eff["momentum"] < base["momentum"]
    assert eff["relative_strength"] < base["relative_strength"]
    # Total score-factor weight preserved by the renormalization.
    assert abs(sum(eff[f] for f in _SCORE_FACTORS) - sum(base[f] for f in _SCORE_FACTORS)) < 1e-6


def test_decorrelation_toggle_changes_weights():
    on = load_config(); on.scoring.decorrelate = True
    off = load_config(); off.scoring.decorrelate = False
    ohlcv, sectors = make_universe(40)
    scans, report = MarketScannerAgent(on).scan(ohlcv, sectors)
    w_on = OpportunityScoringAgent(on)._effective_weights(OpportunityScoringAgent(on)._standardize(
        OpportunityScoringAgent(on)._raw_factor_frame([s for s in scans if s.passed])))
    w_off = OpportunityScoringAgent(off)._effective_weights(OpportunityScoringAgent(off)._standardize(
        OpportunityScoringAgent(off)._raw_factor_frame([s for s in scans if s.passed])))
    assert w_on != w_off


def test_signed_agreement_not_inflated_by_magnitude_factors():
    """Regression guard for the old bug: magnitude factors contributed |z| and
    always read as 'agreeing'. Signed agreement must fall when factors point
    opposite ways."""
    scorer = OpportunityScoringAgent(load_config())
    # Evidence is normalized by winsor_z (3.0), so full alignment sits at the cap.
    aligned = pd.Series({f: 3.0 for f in _SCORE_FACTORS})
    mixed = pd.Series({f: (3.0 if i % 2 == 0 else -3.0) for i, f in enumerate(_SCORE_FACTORS)})
    assert scorer._agreement(aligned) > 0.9
    assert scorer._agreement(mixed) < 0.5


def test_event_is_vol_scaled():
    scorer = OpportunityScoringAgent(load_config())
    # A 3% gap is an event for a low-ATR name, but not for a high-ATR one.
    calm = _scan(relative_volume=1.0, gap_pct=0.03, atr_pct=0.005, vol_expansion_ratio=1.0)
    stormy = _scan(relative_volume=1.0, gap_pct=0.03, atr_pct=0.05, vol_expansion_ratio=1.0)
    assert scorer._event_raw(calm) == 1.0
    assert scorer._event_raw(stormy) == 0.0


def test_weights_configurable_change_ranking():
    ohlcv, sectors = make_universe(40)
    mom = load_config(); mom.scoring.weights = {k: 0.0 for k in mom.scoring.weights}; mom.scoring.weights["momentum"] = 1.0
    liq = load_config(); liq.scoring.weights = {k: 0.0 for k in liq.scoring.weights}; liq.scoring.weights["liquidity"] = 1.0
    assert _score(mom, ohlcv, sectors)[0].symbol != _score(liq, ohlcv, sectors)[0].symbol
