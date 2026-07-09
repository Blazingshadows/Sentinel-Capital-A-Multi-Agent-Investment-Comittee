"""Uniform fit/predict/save/load wrapper around the three model
architectures the search loop treats interchangeably: LightGBM (leaf-wise
histogram GBM), XGBoost (level-wise histogram GBM -- different inductive
bias/regularization than LightGBM), and RandomForest (bagged trees --
structurally uncorrelated errors from either boosting model, cheap ensemble
diversity). Labels are the same {0, 1, 2} = {bearish, neutral, bullish}
classes `agents/forecasting.py::LABEL_TO_CLASS` already defines -- this
module doesn't redefine labeling, only how a model is fit to it.

Each architecture is further parameterized by a `ModelConfig` (a named
hyperparameter preset from `config.ALGO_MODEL_PRESETS`), so the search
treats "LightGBM with conservative regularization" and "LightGBM with
aggressive regularization" as distinct candidates -- see
`build_model_configs`.
"""

from dataclasses import dataclass
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier

from backend.committee.config import ALGO_EARLY_STOPPING_ROUNDS, ALGO_MAX_BOOST_ROUNDS

MODEL_ARCHITECTURES = ("lightgbm", "xgboost", "random_forest")
MODEL_FILE_EXT = {"lightgbm": "txt", "xgboost": "json", "random_forest": "joblib"}

# Below this many validation rows, early stopping's signal is too noisy to
# trust -- fall back to a fixed round count instead.
MIN_VALIDATION_ROWS = 50
DEFAULT_BOOST_ROUNDS = 200


@dataclass(frozen=True)
class ModelConfig:
    name: str
    architecture: str
    params: dict


def build_model_configs(presets: dict[str, dict[str, dict]]) -> list[ModelConfig]:
    """Flattens `config.ALGO_MODEL_PRESETS` (architecture -> preset name ->
    hyperparams) into the flat list of candidates the search iterates over."""
    return [
        ModelConfig(name=f"{architecture}_{preset_name}", architecture=architecture, params=dict(params))
        for architecture, arch_presets in presets.items()
        for preset_name, params in arch_presets.items()
    ]


@dataclass
class FittedModel:
    model_type: str
    native: object


def fit_model(
    config: ModelConfig, train_x: pd.DataFrame, train_y: pd.Series,
    val_x: pd.DataFrame | None = None, val_y: pd.Series | None = None, seed: int = 42,
) -> FittedModel:
    has_validation = val_x is not None and val_y is not None and len(val_x) >= MIN_VALIDATION_ROWS

    if config.architecture == "lightgbm":
        params = {"objective": "multiclass", "num_class": 3, "verbosity": -1, "seed": seed, **config.params}
        train_set = lgb.Dataset(train_x, label=train_y)
        if has_validation:
            valid_set = lgb.Dataset(val_x, label=val_y, reference=train_set)
            booster = lgb.train(
                params=params, train_set=train_set, num_boost_round=ALGO_MAX_BOOST_ROUNDS,
                valid_sets=[valid_set], callbacks=[lgb.early_stopping(ALGO_EARLY_STOPPING_ROUNDS, verbose=False)],
            )
        else:
            booster = lgb.train(params=params, train_set=train_set, num_boost_round=DEFAULT_BOOST_ROUNDS)
        return FittedModel("lightgbm", booster)

    if config.architecture == "xgboost":
        model = XGBClassifier(
            objective="multi:softprob",
            verbosity=0,
            random_state=seed,
            n_estimators=ALGO_MAX_BOOST_ROUNDS if has_validation else config.params.get("n_estimators", DEFAULT_BOOST_ROUNDS),
            early_stopping_rounds=ALGO_EARLY_STOPPING_ROUNDS if has_validation else None,
            **{k: v for k, v in config.params.items() if k != "n_estimators"},
        )
        if has_validation:
            model.fit(train_x, train_y, eval_set=[(val_x, val_y)], verbose=False)
        else:
            model.fit(train_x, train_y)
        return FittedModel("xgboost", model)

    if config.architecture == "random_forest":
        model = RandomForestClassifier(random_state=seed, n_jobs=-1, **config.params)
        model.fit(train_x, train_y)
        return FittedModel("random_forest", model)

    raise ValueError(f"unknown architecture: {config.architecture!r} (expected one of {MODEL_ARCHITECTURES})")


def predict_proba(fitted: FittedModel, x: pd.DataFrame) -> np.ndarray:
    """Always returns an (n, 3) array ordered [P(bearish), P(neutral), P(bullish)]."""
    if fitted.model_type == "lightgbm":
        return fitted.native.predict(x)
    return fitted.native.predict_proba(x)


def save_model(fitted: FittedModel, path_stem: Path) -> Path:
    path_stem.parent.mkdir(parents=True, exist_ok=True)
    path = path_stem.with_suffix(f".{MODEL_FILE_EXT[fitted.model_type]}")
    if fitted.model_type in ("lightgbm", "xgboost"):
        fitted.native.save_model(str(path))
    else:
        joblib.dump(fitted.native, path)
    return path


def load_model(model_type: str, path: Path) -> FittedModel:
    if model_type == "lightgbm":
        return FittedModel("lightgbm", lgb.Booster(model_file=str(path)))
    if model_type == "xgboost":
        model = XGBClassifier()
        model.load_model(str(path))
        return FittedModel("xgboost", model)
    if model_type == "random_forest":
        return FittedModel("random_forest", joblib.load(path))
    raise ValueError(f"unknown model_type: {model_type!r} (expected one of {MODEL_ARCHITECTURES})")
