import lightgbm as lgb
import numpy as np
import pandas as pd

from backend.committee.agents import forecasting
from backend.committee.market_data.context import MarketContext
from backend.committee.schemas import Decision
from backend.committee.tests.conftest import synthetic_ohlcv


def test_build_features_only_uses_past_data():
    """A feature computed at row i must be identical whether or not later
    rows exist -- otherwise the model would be trained with lookahead."""
    ohlcv = synthetic_ohlcv(n=100)
    full = forecasting.build_features(ohlcv)
    truncated = forecasting.build_features(ohlcv.iloc[:60])

    pd.testing.assert_frame_equal(full.iloc[:60], truncated, check_exact=False, rtol=1e-9)


def test_build_labels_flags_a_large_move_on_a_calm_series():
    n = 30
    # Smooth, near-zero-volatility trend so rolling vol stays tiny and the
    # min_deadzone floor governs.
    closes = pd.Series(100.0 + np.arange(n) * 0.01, index=pd.date_range("2026-01-01", periods=n, freq="15min"))
    closes.iloc[18] = closes.iloc[15] * 0.9  # -10% move, far beyond any reasonable deadzone
    ohlcv = pd.DataFrame({"Close": closes})

    labels = forecasting.build_labels(ohlcv, lookahead=3)

    assert labels.iloc[15] == -1


def test_deadzone_scales_with_volatility():
    """The same size of move should register as signal on a calm stock but
    get swallowed as noise on a volatile one -- the whole point of scaling
    the deadzone instead of using one fixed return threshold for every
    stock."""
    n = 40
    idx = pd.date_range("2026-01-01", periods=n, freq="15min")
    rng = np.random.default_rng(3)
    noise = rng.normal(0, 1, n)

    low_vol_closes = pd.Series(100 * np.cumprod(1 + noise * 0.0005), index=idx)
    high_vol_closes = pd.Series(100 * np.cumprod(1 + noise * 0.01), index=idx)

    i = 25
    low_vol_closes.iloc[i + 3] = low_vol_closes.iloc[i] * 1.003
    high_vol_closes.iloc[i + 3] = high_vol_closes.iloc[i] * 1.003

    low_labels = forecasting.build_labels(pd.DataFrame({"Close": low_vol_closes}), lookahead=3)
    high_labels = forecasting.build_labels(pd.DataFrame({"Close": high_vol_closes}), lookahead=3)

    assert low_labels.iloc[i] == 1  # +0.3% is a real move for a calm stock
    assert high_labels.iloc[i] == 0  # +0.3% is noise for a volatile one


def test_analyze_degrades_to_wait_without_a_trained_model(monkeypatch, synthetic_context, tmp_path):
    monkeypatch.setattr(forecasting, "_model_cache", None)
    monkeypatch.setattr(forecasting, "_model_load_attempted", False)
    monkeypatch.setattr(forecasting, "FORECAST_MODEL_PATH", str(tmp_path / "missing_model.txt"))
    monkeypatch.setattr(forecasting, "FORECAST_META_PATH", str(tmp_path / "missing_meta.json"))

    output = forecasting.analyze(synthetic_context)

    assert output.decision == Decision.WAIT
    assert output.confidence == 0.0


def test_analyze_produces_a_valid_output_with_a_trained_model(monkeypatch):
    ohlcv = synthetic_ohlcv(n=200)
    features = forecasting.build_features(ohlcv)
    labels = forecasting.build_labels(ohlcv)
    combined = features.join(labels.rename("label")).dropna()

    classes = combined["label"].map(forecasting.LABEL_TO_CLASS)
    booster = lgb.train(
        params={"objective": "multiclass", "num_class": 3, "verbosity": -1, "min_data_in_leaf": 5},
        train_set=lgb.Dataset(combined[forecasting.FEATURE_COLUMNS], label=classes),
        num_boost_round=10,
    )
    bundle = forecasting._ModelBundle(booster=booster, feature_importance={"rsi_14": 1.0})

    monkeypatch.setattr(forecasting, "_model_cache", bundle)
    monkeypatch.setattr(forecasting, "_model_load_attempted", True)

    context = MarketContext(symbol="TEST", ohlcv=ohlcv, headlines=[], fundamentals={}, sector=None, context_flags=["normal"])
    output = forecasting.analyze(context)

    assert output.agent == "Forecasting"
    assert output.decision in (Decision.BUY, Decision.SELL, Decision.WAIT)
    assert 0.0 <= output.confidence <= 1.0
    assert output.evidence
