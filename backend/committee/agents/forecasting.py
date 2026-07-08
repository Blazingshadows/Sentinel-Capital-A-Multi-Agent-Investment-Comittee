"""Forecasting Agent — a genuinely different point of view from the LLM
agents: a LightGBM classifier pattern-matching on lagged OHLCV/indicator
features, with zero language-based reasoning involved. Trained offline by
`scripts/train_forecasting_model.py`; this module only does feature
engineering (shared with training) and inference.

Deliberately a gradient-boosted tree, not an LSTM: trains in seconds on
modest intraday history, is far less prone to overfitting a short window,
and gives feature importances as a built-in explainability story instead of
an opaque hidden state.
"""

import json
from pathlib import Path

import lightgbm as lgb
import pandas as pd

from backend.committee.agents.technical import compute_ema, compute_macd, compute_rsi
from backend.committee.config import (
    FORECAST_DEADZONE_MIN_RETURN,
    FORECAST_DEADZONE_VOL_MULTIPLIER,
    FORECAST_LAG_PERIODS,
    FORECAST_LOOKAHEAD_BARS,
    FORECAST_META_PATH,
    FORECAST_MODEL_PATH,
    FORECAST_VOLATILITY_WINDOW,
)
from backend.committee.market_data.context import MarketContext
from backend.committee.schemas import AgentOutput, Decision

AGENT_NAME = "Forecasting"

FEATURE_COLUMNS = (
    [f"lag_return_{n}" for n in FORECAST_LAG_PERIODS]
    + ["rsi_14", "macd_hist", "ema_diff", "volatility", "volume_change"]
)

# LightGBM needs non-negative integer classes; map to/from our {-1, 0, 1} labels.
LABEL_TO_CLASS = {-1: 0, 0: 1, 1: 2}
CLASS_TO_LABEL = {v: k for k, v in LABEL_TO_CLASS.items()}


def build_features(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Shared by training and inference so the model always sees the exact
    same feature definitions it was trained on."""
    closes = ohlcv["Close"]
    volume = ohlcv["Volume"]

    features = pd.DataFrame(index=ohlcv.index)
    for n in FORECAST_LAG_PERIODS:
        features[f"lag_return_{n}"] = closes.pct_change(periods=n)

    features["rsi_14"] = compute_rsi(closes) / 100.0  # scale to [0, 1] like the other features
    _, _, macd_hist = compute_macd(closes)
    features["macd_hist"] = macd_hist / closes  # normalize by price so it's comparable across stocks

    ema_fast = compute_ema(closes, 20)
    ema_slow = compute_ema(closes, 50)
    features["ema_diff"] = (ema_fast - ema_slow) / ema_slow

    features["volatility"] = closes.pct_change().rolling(FORECAST_VOLATILITY_WINDOW).std()
    features["volume_change"] = volume.pct_change().replace([float("inf"), float("-inf")], float("nan"))

    return features[FEATURE_COLUMNS]


def build_labels(ohlcv: pd.DataFrame, lookahead: int = FORECAST_LOOKAHEAD_BARS,
                  vol_multiplier: float = FORECAST_DEADZONE_VOL_MULTIPLIER,
                  min_deadzone: float = FORECAST_DEADZONE_MIN_RETURN) -> pd.Series:
    """Bullish/bearish requires clearing a threshold scaled to this stock's
    own rolling volatility over the `lookahead`-bar horizon, not a fixed
    return -- a flat threshold mislabels a calm stock's noise as a real move
    and a volatile stock's real moves as noise when pooled together for
    training. `min_deadzone` floors it so a near-zero rolling vol (a dead
    market open) can't collapse the threshold to ~0.
    """
    closes = ohlcv["Close"]
    forward_return = closes.shift(-lookahead) / closes - 1

    per_bar_vol = closes.pct_change().rolling(FORECAST_VOLATILITY_WINDOW).std()
    horizon_vol = per_bar_vol * (lookahead ** 0.5)  # returns compound; variance scales with time under a random-walk assumption
    deadzone = (vol_multiplier * horizon_vol).clip(lower=min_deadzone)

    labels = pd.Series(0, index=ohlcv.index)
    labels[forward_return > deadzone] = 1
    labels[forward_return < -deadzone] = -1
    labels[forward_return.isna() | deadzone.isna()] = pd.NA
    return labels


class _ModelBundle:
    def __init__(self, booster: lgb.Booster, feature_importance: dict[str, float]):
        self.booster = booster
        self.feature_importance = feature_importance


_model_cache: _ModelBundle | None = None
_model_load_attempted = False


def _load_model() -> _ModelBundle | None:
    global _model_cache, _model_load_attempted
    if _model_load_attempted:
        return _model_cache
    _model_load_attempted = True

    model_path = Path(FORECAST_MODEL_PATH)
    meta_path = Path(FORECAST_META_PATH)
    if not model_path.exists() or not meta_path.exists():
        return None

    booster = lgb.Booster(model_file=str(model_path))
    meta = json.loads(meta_path.read_text())
    _model_cache = _ModelBundle(booster=booster, feature_importance=meta.get("feature_importance", {}))
    return _model_cache


def analyze(context: MarketContext) -> AgentOutput:
    bundle = _load_model()
    if bundle is None:
        return AgentOutput(
            agent=AGENT_NAME,
            decision=Decision.WAIT,
            confidence=0.0,
            reasoning="No trained forecasting model found — run scripts/train_forecasting_model.py first.",
            evidence=[],
        )

    features = build_features(context.ohlcv)
    latest = features.iloc[[-1]]
    if latest.isna().any(axis=None):
        return AgentOutput(
            agent=AGENT_NAME,
            decision=Decision.WAIT,
            confidence=0.0,
            reasoning="Insufficient history to compute all forecasting features this cycle.",
            evidence=[],
        )

    probabilities = bundle.booster.predict(latest)[0]  # [P(bearish), P(neutral), P(bullish)]
    predicted_class = int(probabilities.argmax())
    predicted_label = CLASS_TO_LABEL[predicted_class]
    confidence = float(probabilities[predicted_class])

    decision = {-1: Decision.SELL, 0: Decision.WAIT, 1: Decision.BUY}[predicted_label]

    top_features = sorted(bundle.feature_importance.items(), key=lambda kv: kv[1], reverse=True)[:3]
    evidence = [f"{name}={latest[name].iloc[0]:.4f} (importance={importance:.2f})" for name, importance in top_features]

    return AgentOutput(
        agent=AGENT_NAME,
        decision=decision,
        confidence=round(confidence, 4),
        reasoning=(
            f"LightGBM forecast over next {FORECAST_LOOKAHEAD_BARS} bars: "
            f"P(bearish)={probabilities[0]:.2f}, P(neutral)={probabilities[1]:.2f}, P(bullish)={probabilities[2]:.2f}."
        ),
        evidence=evidence,
    )
