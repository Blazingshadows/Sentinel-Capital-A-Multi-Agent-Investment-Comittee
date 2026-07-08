import numpy as np
import pandas as pd
import pytest

from backend.committee.signals import SIGNAL_REGISTRY, STYLES


def _synthetic_ohlcv(n: int = 120, seed: int = 7) -> pd.DataFrame:
    """Unlike `tests.conftest.synthetic_ohlcv`, volume varies here -- several
    signals (volume z-score, OBV, VWAP deviation) are degenerate (all-NaN)
    under constant volume, so a fixed-variance series would silently skip
    real coverage of those signals."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0003, 0.004, n)
    closes = 1500.0 * np.cumprod(1 + returns)
    volume = rng.integers(5_000, 50_000, n).astype(float)
    index = pd.date_range("2026-01-01 09:15", periods=n, freq="5min")
    return pd.DataFrame(
        {
            "Open": closes * (1 + rng.normal(0, 0.0005, n)),
            "High": closes * 1.002,
            "Low": closes * 0.998,
            "Close": closes,
            "Volume": volume,
        },
        index=index,
    )


def _synthetic_panel(symbols: list[str], n: int = 120) -> pd.DataFrame:
    return pd.DataFrame({s: _synthetic_ohlcv(n=n, seed=hash(s) % 1000)["Close"] for s in symbols})


@pytest.mark.parametrize("name", [n for n, spec in SIGNAL_REGISTRY.items() if not spec.needs_panel])
def test_single_symbol_signal_is_causal(name):
    """A signal value at row i must be identical whether or not later rows
    exist -- otherwise a model trained on it would see lookahead."""
    spec = SIGNAL_REGISTRY[name]
    ohlcv = _synthetic_ohlcv()
    full = spec.fn(ohlcv, **spec.params)
    truncated = spec.fn(ohlcv.iloc[:60], **spec.params)

    pd.testing.assert_series_equal(full.iloc[:60], truncated, check_exact=False, rtol=1e-9, check_names=False)


@pytest.mark.parametrize("name", [n for n, spec in SIGNAL_REGISTRY.items() if spec.needs_panel])
def test_cross_sectional_signal_is_causal(name):
    spec = SIGNAL_REGISTRY[name]
    symbols = ["AAA", "BBB", "CCC"]
    panel = _synthetic_panel(symbols)
    ohlcv = _synthetic_ohlcv(seed=hash("AAA") % 1000)

    full = spec.fn(ohlcv, symbol="AAA", panel=panel, **spec.params)
    truncated = spec.fn(ohlcv.iloc[:60], symbol="AAA", panel=panel, **spec.params)

    pd.testing.assert_series_equal(full.iloc[:60], truncated, check_exact=False, rtol=1e-9, check_names=False)


def test_cross_sectional_signal_degrades_gracefully_without_panel():
    spec = SIGNAL_REGISTRY["xs_relative_strength"]
    ohlcv = _synthetic_ohlcv()
    result = spec.fn(ohlcv, symbol="AAA", panel=pd.DataFrame(), **spec.params)
    assert result.isna().all()


def test_registry_has_every_style_represented():
    assert len(STYLES) >= 5
    for style in STYLES:
        assert any(spec.style == style for spec in SIGNAL_REGISTRY.values())
