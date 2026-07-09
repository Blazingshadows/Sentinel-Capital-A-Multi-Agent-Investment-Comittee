"""Walk-forward search over (feature-subset x model-config x confidence-
threshold) candidates, ranked by backtested Sharpe -- not classification
accuracy -- consistent with the project's cost-aware profit objective.
Extends the single 80/20 per-symbol holdout in
`scripts/train_forecasting_model.py` to multiple expanding-window folds,
pooled across `WATCHLIST`, so a candidate's score isn't just one lucky/
unlucky split. Model configs are named hyperparameter presets
(`algo_engine.models.build_model_configs`), not just architecture names, so
tuning capacity/regularization is part of the same search rather than a
separate pass. Thresholds are swept post-hoc over each fold's already-
computed probabilities -- no extra model fits.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import vectorbt as vbt

from backend.committee.agents.forecasting import LABEL_TO_CLASS, build_labels
from backend.committee.algo_engine.features import FeatureSubset, build_all_signals, iter_feature_subsets
from backend.committee.algo_engine.models import FittedModel, ModelConfig, build_model_configs, fit_model, predict_proba
from backend.committee.baseline.metrics import compute_returns_stats
from backend.committee.baseline.vectorbt_baseline import FEE_RATE, SLIPPAGE_RATE, build_price_panel
from backend.committee.config import (
    ALGO_BACKTEST_FREQ,
    ALGO_CONFIDENCE_THRESHOLDS,
    ALGO_MODEL_PRESETS,
    ALGO_RANDOM_SUBSET_COUNT,
    ALGO_SEED,
    ALGO_TRAIN_INTERVAL,
    ALGO_TRAIN_PERIOD,
    ALGO_VALIDATION_FRACTION,
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
    model_config: ModelConfig
    threshold: float
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


def pooled_training_set(
    all_symbol_data: list[SymbolData], subset: FeatureSubset, fraction: float, val_fraction: float = 0.0,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame | None, pd.Series | None] | None:
    """Pools training rows from every symbol up to the same *proportional*
    cutoff (each symbol's own history may differ in length/coverage, so a
    proportional cutoff approximates a shared point in time without
    requiring a fully reindexed common calendar). If `val_fraction` > 0, the
    tail of each symbol's slice is carved off as a validation set (still
    strictly earlier than the fold's test slice) for early stopping --
    returns (train_x, train_y, None, None) when `val_fraction` is 0 or too
    little data is available to carve a validation set."""
    feature_cols = list(subset.features)
    train_frames_x, train_frames_y, val_frames_x, val_frames_y = [], [], [], []
    for sd in all_symbol_data:
        cutoff = int(len(sd.signals) * fraction)
        if cutoff < MIN_TRAIN_ROWS_PER_FOLD:
            continue
        x = sd.signals[feature_cols].iloc[:cutoff]
        y = sd.labels.iloc[:cutoff]
        combined = x.join(y.rename("label")).dropna()
        if combined.empty:
            continue
        combined_y = combined["label"].map(LABEL_TO_CLASS).astype(int)

        if val_fraction > 0 and len(combined) >= MIN_TRAIN_ROWS_PER_FOLD * 2:
            split_idx = int(len(combined) * (1 - val_fraction))
            train_frames_x.append(combined[feature_cols].iloc[:split_idx])
            train_frames_y.append(combined_y.iloc[:split_idx])
            val_frames_x.append(combined[feature_cols].iloc[split_idx:])
            val_frames_y.append(combined_y.iloc[split_idx:])
        else:
            train_frames_x.append(combined[feature_cols])
            train_frames_y.append(combined_y)

    if not train_frames_x:
        return None
    train_x, train_y = pd.concat(train_frames_x), pd.concat(train_frames_y)
    if len(train_x) < MIN_TRAIN_ROWS_PER_FOLD or train_y.nunique() < 2:
        return None

    val_x, val_y = (pd.concat(val_frames_x), pd.concat(val_frames_y)) if val_frames_x else (None, None)
    return train_x, train_y, val_x, val_y


def _position_from_probs(probs: np.ndarray, threshold: float) -> np.ndarray:
    """Long when P(bullish) beats the strongest other class by more than
    `threshold`; flat otherwise (no shorting, matching the committee's own
    paper-trading constraints). `threshold=0` reduces to plain argmax-
    bullish."""
    bearish, neutral, bullish = probs[:, 0], probs[:, 1], probs[:, 2]
    margin = bullish - np.maximum(bearish, neutral)
    return (margin > threshold).astype(int)


def _backtest_position(position: pd.Series, close: pd.Series) -> float | None:
    """Backtests a long/flat position series with the same fee/slippage
    assumptions and stats methodology as the SMA-crossover baseline, so
    candidate scores are directly comparable to it."""
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
    test_start_fraction: float, test_end_fraction: float, thresholds: list[float],
) -> dict[float, float]:
    """Backtests one already-fitted fold model against one symbol's test
    slice, at every threshold in `thresholds` -- the model itself is shared
    across every symbol and threshold evaluated at this fold (see
    `run_search`), so predict_proba runs once per (fold, symbol) regardless
    of how many thresholds are swept."""
    n = len(target.signals)
    test_start, test_end = int(n * test_start_fraction), int(n * test_end_fraction)

    feature_cols = list(subset.features)
    test_x_full = target.signals[feature_cols].iloc[test_start:test_end]
    valid_index = test_x_full.dropna().index
    if len(valid_index) < MIN_TEST_ROWS_PER_FOLD:
        return {}
    test_x = test_x_full.loc[valid_index]
    test_close = target.close.loc[valid_index]

    try:
        probs = predict_proba(fitted, test_x)
    except Exception:
        return {}

    results: dict[float, float] = {}
    for threshold in thresholds:
        position = pd.Series(_position_from_probs(probs, threshold), index=test_x.index)
        sharpe = _backtest_position(position, test_close)
        if sharpe is not None:
            results[threshold] = sharpe
    return results


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
    model_configs: list[ModelConfig] | None = None,
    thresholds: list[float] = ALGO_CONFIDENCE_THRESHOLDS,
    random_count: int = ALGO_RANDOM_SUBSET_COUNT,
    seed: int = ALGO_SEED,
) -> list[CandidateResult]:
    """Trains every (feature subset x model config) candidate across all
    walk-forward folds of every symbol, sweeps every threshold on the
    resulting probabilities, and returns a leaderboard sorted by average
    backtested Sharpe, best first. Pass a pre-loaded `symbol_data` (from
    `load_universe`) to avoid refetching; otherwise it's loaded internally
    from `symbols`/`period`/`interval`. Pass `model_configs` to override the
    default `config.ALGO_MODEL_PRESETS`-derived set (e.g. for a narrower
    tuning pass)."""
    if symbol_data is None:
        symbol_data = load_universe(symbols, period, interval)
    if model_configs is None:
        model_configs = build_model_configs(ALGO_MODEL_PRESETS)

    subsets = iter_feature_subsets(random_count=random_count, seed=seed)
    fold_fractions = _fold_fractions(folds)
    results: list[CandidateResult] = []

    for subset in subsets:
        for config in model_configs:
            fold_sharpes: dict[float, list[float]] = {t: [] for t in thresholds}
            for train_fraction, test_start_fraction, test_end_fraction in fold_fractions:
                training_set = pooled_training_set(symbol_data, subset, train_fraction, val_fraction=ALGO_VALIDATION_FRACTION)
                if training_set is None:
                    continue
                train_x, train_y, val_x, val_y = training_set
                try:
                    fitted = fit_model(config, train_x, train_y, val_x, val_y, seed=seed)
                except Exception:
                    continue

                for target in symbol_data:
                    per_threshold = _evaluate_symbol_on_fold(fitted, subset, target, test_start_fraction, test_end_fraction, thresholds)
                    for threshold, sharpe in per_threshold.items():
                        fold_sharpes[threshold].append(sharpe)

            for threshold in thresholds:
                sharpes = fold_sharpes[threshold]
                avg_sharpe = float(np.mean(sharpes)) if sharpes else float("-inf")
                results.append(CandidateResult(
                    subset_name=subset.name, model_config=config, threshold=threshold, features=subset.features,
                    sharpe=avg_sharpe, folds_evaluated=len(sharpes),
                ))

    results.sort(key=lambda r: r.sharpe, reverse=True)
    return results
