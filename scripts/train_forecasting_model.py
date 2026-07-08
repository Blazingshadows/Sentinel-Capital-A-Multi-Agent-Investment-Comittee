"""Trains the Forecasting agent's LightGBM classifier on pooled watchlist
history. Run this once (and re-run periodically) before the Forecasting
agent can produce real predictions — until then it degrades to WAIT.

Usage:
    python scripts/train_forecasting_model.py
"""

import json
import sys
from pathlib import Path

import lightgbm as lgb
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.committee.agents.forecasting import (  # noqa: E402
    FEATURE_COLUMNS,
    LABEL_TO_CLASS,
    build_features,
    build_labels,
)
from backend.committee.config import (  # noqa: E402
    FORECAST_META_PATH,
    FORECAST_MIN_TRAINING_ROWS,
    FORECAST_MODEL_PATH,
    FORECAST_TRAIN_INTERVAL,
    FORECAST_TRAIN_PERIOD,
    WATCHLIST,
)
from backend.committee.market_data.prices import fetch_ohlcv  # noqa: E402

HOLDOUT_FRACTION = 0.2


def build_dataset(symbols: list[str]) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """Per-symbol time-based split (last HOLDOUT_FRACTION of each symbol's
    bars held out), then pooled across symbols — avoids leaking future bars
    from the same symbol into training while still testing on every symbol.
    """
    train_x, train_y, test_x, test_y = [], [], [], []

    for symbol in symbols:
        try:
            ohlcv = fetch_ohlcv(symbol, period=FORECAST_TRAIN_PERIOD, interval=FORECAST_TRAIN_INTERVAL)
        except Exception as exc:
            print(f"  skipping {symbol}: {exc}")
            continue

        features = build_features(ohlcv)
        labels = build_labels(ohlcv)
        combined = features.join(labels.rename("label")).dropna()
        if len(combined) < 50:
            print(f"  skipping {symbol}: only {len(combined)} usable rows")
            continue

        split_idx = int(len(combined) * (1 - HOLDOUT_FRACTION))
        train_part, test_part = combined.iloc[:split_idx], combined.iloc[split_idx:]

        train_x.append(train_part[FEATURE_COLUMNS])
        train_y.append(train_part["label"])
        test_x.append(test_part[FEATURE_COLUMNS])
        test_y.append(test_part["label"])

        print(f"  {symbol}: {len(train_part)} train rows, {len(test_part)} holdout rows")

    return (
        pd.concat(train_x), pd.concat(train_y).astype(int),
        pd.concat(test_x), pd.concat(test_y).astype(int),
    )


def main() -> None:
    print(f"Pulling {FORECAST_TRAIN_PERIOD} of {FORECAST_TRAIN_INTERVAL} history for {len(WATCHLIST)} watchlist symbols...")
    train_x, train_y, test_x, test_y = build_dataset(WATCHLIST)

    if len(train_x) < FORECAST_MIN_TRAINING_ROWS:
        raise SystemExit(
            f"Only {len(train_x)} training rows pooled (need >= {FORECAST_MIN_TRAINING_ROWS}). "
            "Check network access / yfinance availability and try again."
        )

    train_classes = train_y.map(LABEL_TO_CLASS)
    test_classes = test_y.map(LABEL_TO_CLASS)

    print(f"\nTraining LightGBM on {len(train_x)} rows ({train_x.shape[1]} features)...")
    train_set = lgb.Dataset(train_x, label=train_classes)
    booster = lgb.train(
        params={
            "objective": "multiclass",
            "num_class": 3,
            "verbosity": -1,
            "learning_rate": 0.05,
            "num_leaves": 15,
            "min_data_in_leaf": 20,
        },
        train_set=train_set,
        num_boost_round=200,
    )

    predictions = booster.predict(test_x).argmax(axis=1)
    accuracy = accuracy_score(test_classes, predictions)
    print(f"\nHoldout accuracy: {accuracy:.3f} (n={len(test_x)}, 3-class — random baseline is ~0.33)")
    print(classification_report(test_classes, predictions, target_names=["bearish", "neutral", "bullish"]))

    importance = dict(zip(FEATURE_COLUMNS, booster.feature_importance(importance_type="gain").tolist()))
    total_importance = sum(importance.values()) or 1.0
    importance = {k: v / total_importance for k, v in importance.items()}

    model_path = Path(FORECAST_MODEL_PATH)
    meta_path = Path(FORECAST_META_PATH)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(model_path))
    meta_path.write_text(json.dumps({"feature_importance": importance, "holdout_accuracy": accuracy}, indent=2))
    print(f"\nSaved model to {model_path} and metadata to {meta_path}")


if __name__ == "__main__":
    main()
