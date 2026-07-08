"""Uniform fit/predict/save/load wrapper around the three model
architectures the search loop treats interchangeably: LightGBM (leaf-wise
histogram GBM), XGBoost (level-wise histogram GBM -- different inductive
bias/regularization than LightGBM), and RandomForest (bagged trees --
structurally uncorrelated errors from either boosting model, cheap ensemble
diversity). Labels are the same {0, 1, 2} = {bearish, neutral, bullish}
classes `agents/forecasting.py::LABEL_TO_CLASS` already defines -- this
module doesn't redefine labeling, only how a model is fit to it.
"""

from dataclasses import dataclass
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier

MODEL_ARCHITECTURES = ("lightgbm", "xgboost", "random_forest")
MODEL_FILE_EXT = {"lightgbm": "txt", "xgboost": "json", "random_forest": "joblib"}


@dataclass
class FittedModel:
    model_type: str
    native: object


def fit_model(model_type: str, train_x: pd.DataFrame, train_y: pd.Series, seed: int = 42) -> FittedModel:
    if model_type == "lightgbm":
        booster = lgb.train(
            params={
                "objective": "multiclass",
                "num_class": 3,
                "verbosity": -1,
                "learning_rate": 0.05,
                "num_leaves": 15,
                "min_data_in_leaf": 20,
                "seed": seed,
            },
            train_set=lgb.Dataset(train_x, label=train_y),
            num_boost_round=200,
        )
        return FittedModel("lightgbm", booster)

    if model_type == "xgboost":
        model = XGBClassifier(
            objective="multi:softprob",
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            verbosity=0,
            random_state=seed,
        )
        model.fit(train_x, train_y)
        return FittedModel("xgboost", model)

    if model_type == "random_forest":
        model = RandomForestClassifier(
            n_estimators=200,
            max_depth=6,
            min_samples_leaf=20,
            random_state=seed,
            n_jobs=-1,
        )
        model.fit(train_x, train_y)
        return FittedModel("random_forest", model)

    raise ValueError(f"unknown model_type: {model_type!r} (expected one of {MODEL_ARCHITECTURES})")


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
