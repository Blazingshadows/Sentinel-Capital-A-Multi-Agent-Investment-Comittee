"""Walk-forward search over (feature-subset x model-architecture) candidates,
ranked by backtested Sharpe -- not classification accuracy -- consistent
with the project's cost-aware profit objective. Extends the single 80/20
per-symbol holdout in `scripts/train_forecasting_model.py` to multiple
expanding-window folds, pooled across `WATCHLIST`, so a candidate's score
isn't just one lucky/unlucky split.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import vectorbt as vbt

from backend.committee.agents.forecasting import CLASS_TO_LABEL, LABEL_TO_CLASS, build_labels
from backend.committee.algo_engine.features import FeatureSubset, build_all_signals, iter_feature_subsets
from backend.committee.algo_engine.models import FittedModel, fit_model, predict_proba
from backend.committee.baseline.metrics import compute_returns_stats
from backend.committee.baseline.vectorbt_baseline import FEE_RATE, SLIPPAGE_RATE, build_price_panel
from backend.committee.config import (
    ALGO_BACKTEST_FREQ,
    ALGO_MODEL_ARCHITECTURES,
    ALGO_SEED,
    ALGO_TRAIN_INTERVAL,
    ALGO_TRAIN_PERIOD,
    ALGO_WALK_FORWARD_FOLDS,
    BUYING_POWER,
    WATCHLIST,
)
from backend.committee.market_data.prices import fetch_ohlcv

MIN_TRAIN_ROWS_PER_FOLD = 50
MIN_TEST_ROWS_PER_FOLD = 5


@dataclass
class SymbolData:
    symbol: str
    signals: pd.DataFrame
    labels: pd.Series
    close: pd.Series


@dataclass
class CandidateResult:
    subset_name: str
    model_type: str
    features: tuple[str, ...]
    sharpe: float
    folds_evaluated: int


def _load_symbol_data(symbol: str, panel: pd.DataFrame, period: str, interval: str) -> SymbolData | None:
    try:
        ohlcv = fetch_ohlcv(symbol, period=period, interval=interval)
    except Exception:
        return None
    if len(ohlcv) < 50:
        return None
    signals = build_all_signals(ohlcv, symbol=symbol, panel=panel)
    labels = build_labels(ohlcv)
    return SymbolData(symbol=symbol, signals=signals, labels=labels, close=ohlcv["Close"])


def _fold_fractions(folds: int) -> list[tuple[float, float, float]]:
    """`folds` equal-sized chunks as *fractions* of any series' length (0..1),
    shared across every symbol so one model fit per fold can be reused for
    every symbol's test slice instead of refitting per symbol -- refitting
    per (symbol, fold) instead of once per fold made the search an order of
    magnitude slower for no accuracy benefit, since the pooled training set
    at a given fold is already nearly identical across symbols. Returns one
    (train_fraction, test_start_fraction, test_end_fraction) triple per
    chunk after the first; the first chunk is train-only, so this yields
    `folds - 1` evaluated folds."""
    if folds < 2:
        return []
    edges = np.linspace(0.0, 1.0, folds + 1)
    return [(edges[i], edges[i], edges[i + 1]) for i in range(1, folds)]


def pooled_training_set(all_symbol_data: list[SymbolData], subset: FeatureSubset, fraction: float) -> tuple[pd.DataFrame, pd.Series] | None:
    """Pools training rows from every symbol up to the same *proportional*
    cutoff (each symbol's own history may differ in length/coverage, so a
    proportional cutoff approximates a shared point in time without
    requiring a fully reindexed common calendar)."""
    feature_cols = list(subset.features)
    frames_x, frames_y = [], []
    for sd in all_symbol_data:
        cutoff = int(len(sd.signals) * fraction)
        if cutoff < MIN_TRAIN_ROWS_PER_FOLD:
            continue
        x = sd.signals[feature_cols].iloc[:cutoff]
        y = sd.labels.iloc[:cutoff]
        combined = x.join(y.rename("label")).dropna()
        if combined.empty:
            continue
        frames_x.append(combined[feature_cols])
        frames_y.append(combined["label"].map(LABEL_TO_CLASS).astype(int))

    if not frames_x:
        return None
    train_x, train_y = pd.concat(frames_x), pd.concat(frames_y)
    if len(train_x) < MIN_TRAIN_ROWS_PER_FOLD or train_y.nunique() < 2:
        return None
    return train_x, train_y


def _backtest_predictions(predicted_label: pd.Series, close: pd.Series) -> float | None:
    """Turns a per-bar predicted direction into a long/flat position (no
    shorting, matching the committee's own paper-trading constraints) and
    backtests it with the same fee/slippage assumptions and stats
    methodology as the SMA-crossover baseline, so candidate scores are
    directly comparable to it."""
    position = (predicted_label == 1).astype(int)
    if position.nunique() < 2:
        return None  # never traded this fold -- not a meaningful Sharpe

    diffs = position.diff()
    diffs.iloc[0] = position.iloc[0]
    entries = diffs == 1
    exits = diffs == -1

    try:
        portfolio = vbt.Portfolio.from_signals(
            close, entries, exits, init_cash=BUYING_POWER, fees=FEE_RATE, slippage=SLIPPAGE_RATE, freq=ALGO_BACKTEST_FREQ,
        )
        stats = compute_returns_stats(portfolio.value(), freq=ALGO_BACKTEST_FREQ)
        sharpe = float(stats.get("Sharpe Ratio", float("nan")))
    except Exception:
        return None

    return sharpe if np.isfinite(sharpe) else None


def _evaluate_symbol_on_fold(
    fitted: FittedModel, subset: FeatureSubset, target: SymbolData,
    test_start_fraction: float, test_end_fraction: float,
) -> float | None:
    """Backtests one already-fitted fold model against one symbol's test
    slice -- the model itself is shared across every symbol evaluated at
    this fold (see `run_search`), only the test slice is per-symbol."""
    n = len(target.signals)
    test_start, test_end = int(n * test_start_fraction), int(n * test_end_fraction)

    feature_cols = list(subset.features)
    test_x_full = target.signals[feature_cols].iloc[test_start:test_end]
    valid_index = test_x_full.dropna().index
    if len(valid_index) < MIN_TEST_ROWS_PER_FOLD:
        return None
    test_x = test_x_full.loc[valid_index]
    test_close = target.close.loc[valid_index]

    try:
        probs = predict_proba(fitted, test_x)
    except Exception:
        return None

    predicted_class = probs.argmax(axis=1)
    predicted_label = pd.Series(predicted_class, index=test_x.index).map(CLASS_TO_LABEL)
    return _backtest_predictions(predicted_label, test_close)


def load_universe(symbols: list[str] = WATCHLIST, period: str = ALGO_TRAIN_PERIOD, interval: str = ALGO_TRAIN_INTERVAL) -> list[SymbolData]:
    """Pulls OHLCV + builds the signal matrix and labels for every watchlist
    symbol once, so the caller can reuse the same `SymbolData` for both the
    search (`run_search`) and the final full-history ensemble refit
    (`ensemble.build_ensemble`) without refetching."""
    panel = build_price_panel(symbols, period=period, interval=interval)
    symbol_data = [d for d in (_load_symbol_data(s, panel, period, interval) for s in symbols) if d is not None]
    if not symbol_data:
        raise RuntimeError("No watchlist symbols produced usable OHLCV for the AlgoEngine search.")
    return symbol_data


def run_search(
    symbol_data: list[SymbolData] | None = None,
    symbols: list[str] = WATCHLIST,
    period: str = ALGO_TRAIN_PERIOD,
    interval: str = ALGO_TRAIN_INTERVAL,
    folds: int = ALGO_WALK_FORWARD_FOLDS,
    architectures: list[str] = ALGO_MODEL_ARCHITECTURES,
    seed: int = ALGO_SEED,
) -> list[CandidateResult]:
    """Trains every (feature subset x model architecture) candidate across
    all walk-forward folds of every symbol and returns a leaderboard sorted
    by average backtested Sharpe, best first. Pass a pre-loaded
    `symbol_data` (from `load_universe`) to avoid refetching; otherwise it's
    loaded internally from `symbols`/`period`/`interval`."""
    if symbol_data is None:
        symbol_data = load_universe(symbols, period, interval)

    subsets = iter_feature_subsets(seed=seed)
    fold_fractions = _fold_fractions(folds)
    results: list[CandidateResult] = []

    for subset in subsets:
        for model_type in architectures:
            fold_sharpes: list[float] = []
            for train_fraction, test_start_fraction, test_end_fraction in fold_fractions:
                training_set = pooled_training_set(symbol_data, subset, train_fraction)
                if training_set is None:
                    continue
                train_x, train_y = training_set
                try:
                    fitted = fit_model(model_type, train_x, train_y, seed=seed)
                except Exception:
                    continue

                for target in symbol_data:
                    sharpe = _evaluate_symbol_on_fold(fitted, subset, target, test_start_fraction, test_end_fraction)
                    if sharpe is not None:
                        fold_sharpes.append(sharpe)

            avg_sharpe = float(np.mean(fold_sharpes)) if fold_sharpes else float("-inf")
            results.append(CandidateResult(
                subset_name=subset.name, model_type=model_type, features=subset.features,
                sharpe=avg_sharpe, folds_evaluated=len(fold_sharpes),
            ))

    results.sort(key=lambda r: r.sharpe, reverse=True)
    return results
