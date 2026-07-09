import numpy as np
import pandas as pd

from backend.committee.agents import algo_engine, forecasting
from backend.committee.algo_engine.ensemble import EnsembleMember, fuse_probabilities
from backend.committee.algo_engine.features import build_all_signals, iter_feature_subsets
from backend.committee.algo_engine.models import ModelConfig, build_model_configs, fit_model, predict_proba, save_model
from backend.committee.algo_engine.search import _position_from_probs
from backend.committee.config import ALGO_MODEL_PRESETS
from backend.committee.market_data.context import MarketContext
from backend.committee.schemas import Decision
from backend.committee.signals import SIGNAL_REGISTRY, STYLES
from backend.committee.tests.test_signals import _synthetic_ohlcv


def test_iter_feature_subsets_is_deterministic_given_a_seed():
    first = iter_feature_subsets(random_count=5, seed=123)
    second = iter_feature_subsets(random_count=5, seed=123)
    assert [s.features for s in first] == [s.features for s in second]


def test_iter_feature_subsets_covers_styles_and_combined():
    subsets = iter_feature_subsets(random_count=3, seed=1)
    names = {s.name for s in subsets}
    assert "all_combined" in names
    for style in STYLES:
        assert f"style_{style}" in names
    assert sum(n.startswith("random_") for n in names) == 3


def test_fuse_probabilities_weighted_average():
    a = np.array([0.8, 0.1, 0.1])
    b = np.array([0.2, 0.2, 0.6])
    fused = fuse_probabilities([a, b], [3.0, 1.0])
    expected = (3.0 * a + 1.0 * b) / 4.0
    np.testing.assert_allclose(fused, expected)


def test_fuse_probabilities_falls_back_to_uniform_when_weights_are_zero():
    a = np.array([1.0, 0.0, 0.0])
    b = np.array([0.0, 0.0, 1.0])
    fused = fuse_probabilities([a, b], [0.0, 0.0])
    np.testing.assert_allclose(fused, [0.5, 0.0, 0.5])


def test_build_model_configs_creates_one_per_preset():
    configs = build_model_configs(ALGO_MODEL_PRESETS)
    names = {c.name for c in configs}
    assert len(configs) == 9  # 3 architectures x 3 presets
    for architecture, presets in ALGO_MODEL_PRESETS.items():
        for preset_name in presets:
            assert f"{architecture}_{preset_name}" in names


def test_position_from_probs_at_zero_threshold_is_plain_argmax_bullish():
    probs = np.array([[0.1, 0.2, 0.7], [0.6, 0.2, 0.2], [0.3, 0.4, 0.3]])
    position = _position_from_probs(probs, threshold=0.0)
    np.testing.assert_array_equal(position, [1, 0, 0])


def test_fit_model_with_validation_data_early_stops_lightgbm_and_xgboost():
    ohlcv = _synthetic_ohlcv(n=300)
    trend_features = sorted(n for n, spec in SIGNAL_REGISTRY.items() if spec.style == "trend")
    signals = build_all_signals(ohlcv)
    labels = forecasting.build_labels(ohlcv)
    combined = signals[trend_features].join(labels.rename("label")).dropna()
    classes = combined["label"].map(forecasting.LABEL_TO_CLASS).astype(int)

    split = int(len(combined) * 0.7)
    train_x, train_y = combined[trend_features].iloc[:split], classes.iloc[:split]
    val_x, val_y = combined[trend_features].iloc[split:], classes.iloc[split:]

    for architecture in ("lightgbm", "xgboost"):
        params = ALGO_MODEL_PRESETS[architecture]["default"]
        config = ModelConfig(name=f"{architecture}_default", architecture=architecture, params=params)
        fitted = fit_model(config, train_x, train_y, val_x, val_y, seed=1)
        probs = predict_proba(fitted, val_x.iloc[[-1]])
        assert probs.shape == (1, 3)
        np.testing.assert_allclose(probs.sum(axis=1), [1.0], atol=1e-4)


def test_position_from_probs_higher_threshold_requires_a_bigger_margin():
    # bullish (0.38) beats the runner-up (0.32) by 0.06 -- clears a 0 threshold but not 0.10.
    probs = np.array([[0.30, 0.32, 0.38]])
    loose = _position_from_probs(probs, threshold=0.0)
    strict = _position_from_probs(probs, threshold=0.10)
    assert loose[0] == 1
    assert strict[0] == 0


def test_algo_engine_degrades_to_wait_without_a_trained_ensemble(monkeypatch, synthetic_context, tmp_path):
    monkeypatch.setattr(algo_engine, "_manifest_cache", None)
    monkeypatch.setattr(algo_engine, "_manifest_load_attempted", False)
    monkeypatch.setattr(algo_engine, "ALGO_ENSEMBLE_MANIFEST_PATH", str(tmp_path / "missing_manifest.json"))

    output = algo_engine.analyze(synthetic_context)

    assert output.decision == Decision.WAIT
    assert output.confidence == 0.0


def test_algo_engine_produces_a_valid_output_with_a_trained_ensemble(monkeypatch, tmp_path):
    ohlcv = _synthetic_ohlcv(n=200)
    trend_features = sorted(n for n, spec in SIGNAL_REGISTRY.items() if spec.style == "trend")

    signals = build_all_signals(ohlcv)  # no symbol/panel -- trend features don't need them
    labels = forecasting.build_labels(ohlcv)
    combined = signals[trend_features].join(labels.rename("label")).dropna()
    classes = combined["label"].map(forecasting.LABEL_TO_CLASS).astype(int)

    config = ModelConfig(name="lightgbm_default", architecture="lightgbm", params={"num_leaves": 15, "min_data_in_leaf": 20, "learning_rate": 0.05})
    fitted = fit_model(config, combined[trend_features], classes, seed=1)
    saved_path = save_model(fitted, tmp_path / "member0")

    member = EnsembleMember(
        subset_name="style_trend", model_type="lightgbm", config_name="lightgbm_default", threshold=0.05,
        features=tuple(trend_features), weight=1.0, backtest_sharpe=0.5, model_path=str(saved_path),
    )

    monkeypatch.setattr(algo_engine, "_manifest_cache", [member])
    monkeypatch.setattr(algo_engine, "_manifest_load_attempted", True)
    monkeypatch.setattr(algo_engine, "_fitted_cache", {})
    monkeypatch.setattr(algo_engine, "_panel_cache", pd.DataFrame())  # avoid a live watchlist fetch

    context = MarketContext(symbol="TEST", ohlcv=ohlcv, headlines=[], fundamentals={}, sector=None, context_flags=["normal"])
    output = algo_engine.analyze(context)

    assert output.agent == "AlgoEngine"
    assert output.decision in (Decision.BUY, Decision.SELL, Decision.WAIT)
    assert 0.0 <= output.confidence <= 1.0
    assert output.evidence
