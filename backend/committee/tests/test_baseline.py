import numpy as np
import pandas as pd
import pytest
import vectorbt as vbt

from backend.committee.baseline.metrics import compute_returns_stats
from backend.committee.baseline.vectorbt_baseline import run_sma_crossover_baseline


def _synthetic_price_panel(n: int = 200, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01 09:15", periods=n, freq="15min")
    return pd.DataFrame(
        {
            "A": 100 * np.cumprod(1 + rng.normal(0.0002, 0.004, n)),
            "B": 200 * np.cumprod(1 + rng.normal(0.0001, 0.003, n)),
        },
        index=idx,
    )


def test_sma_crossover_baseline_produces_a_portfolio():
    panel = _synthetic_price_panel()
    portfolio = run_sma_crossover_baseline(panel, init_cash=20_000.0)

    assert isinstance(portfolio, vbt.Portfolio)
    values = portfolio.value()
    assert list(values.columns) == ["A", "B"]
    assert len(values) == len(panel)


def test_compute_returns_stats_has_expected_keys():
    panel = _synthetic_price_panel()
    portfolio = run_sma_crossover_baseline(panel, init_cash=20_000.0)
    total_value = portfolio.value().sum(axis=1)

    stats = compute_returns_stats(total_value)

    for key in ["Sharpe Ratio", "Sortino Ratio", "Max Drawdown [%]", "Total Return [%]"]:
        assert key in stats.index


def test_compute_returns_stats_raises_on_insufficient_data():
    with pytest.raises(ValueError):
        compute_returns_stats(pd.Series([20_000.0]))
