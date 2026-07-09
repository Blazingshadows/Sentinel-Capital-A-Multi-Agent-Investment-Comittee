"""Fuses the top-K candidates from `search.py`'s leaderboard into one
ensemble: each survivor is refit on the *full* pooled history (the search
folds only ever saw truncated slices), then combined by Sharpe-weighted
averaging of predicted class probabilities -- simple and explainable
(no second validation split needed for a stacking meta-learner), matching
the project's explainability requirement. Persisted as a JSON manifest plus
one serialized model file per member.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from backend.committee.algo_engine.features import FeatureSubset
from backend.committee.algo_engine.models import fit_model, load_model, predict_proba, save_model
from backend.committee.algo_engine.search import CandidateResult, SymbolData, pooled_training_set
from backend.committee.config import ALGO_VALIDATION_FRACTION


@dataclass
class EnsembleMember:
    subset_name: str
    model_type: str
    config_name: str
    threshold: float
    features: tuple[str, ...]
    weight: float
    backtest_sharpe: float
    model_path: str


def fuse_probabilities(member_probs: list[np.ndarray], weights: list[float]) -> np.ndarray:
    """Weighted average of each member's (n, 3) class-probability array,
    renormalized so rows still sum to 1 -- pure function so the fusion math
    is testable independent of any trained model."""
    total_weight = sum(weights)
    if total_weight <= 0:
        weights = [1.0 / len(weights)] * len(weights)
        total_weight = 1.0
    fused = sum(w * probs for w, probs in zip(weights, member_probs)) / total_weight
    return fused


def build_ensemble(results: list[CandidateResult], symbol_data: list[SymbolData], top_k: int, seed: int, model_dir: Path) -> list[EnsembleMember]:
    finite = [r for r in results if np.isfinite(r.sharpe)]
    top = finite[:top_k]
    if not top:
        raise RuntimeError("No AlgoEngine candidate produced a finite backtested Sharpe -- nothing to ensemble.")

    raw_weights = np.array([max(r.sharpe, 0.0) for r in top])
    weights = raw_weights / raw_weights.sum() if raw_weights.sum() > 0 else np.full(len(top), 1.0 / len(top))

    members: list[EnsembleMember] = []
    for i, (result, weight) in enumerate(zip(top, weights)):
        subset = FeatureSubset(name=result.subset_name, features=result.features)
        training_set = pooled_training_set(symbol_data, subset, fraction=1.0, val_fraction=ALGO_VALIDATION_FRACTION)
        if training_set is None:
            continue
        train_x, train_y, val_x, val_y = training_set

        fitted = fit_model(result.model_config, train_x, train_y, val_x, val_y, seed=seed)
        path_stem = model_dir / f"{i:02d}_{result.subset_name}_{result.model_config.name}"
        saved_path = save_model(fitted, path_stem)

        members.append(EnsembleMember(
            subset_name=result.subset_name, model_type=result.model_config.architecture, config_name=result.model_config.name,
            threshold=result.threshold, features=result.features,
            weight=float(weight), backtest_sharpe=result.sharpe, model_path=str(saved_path),
        ))

    if not members:
        raise RuntimeError("No AlgoEngine candidate had enough full-history training data to fit a final model.")
    return members


def write_manifest(members: list[EnsembleMember], manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"members": [asdict(m) for m in members]}
    manifest_path.write_text(json.dumps(payload, indent=2))


def load_manifest(manifest_path: Path) -> list[EnsembleMember]:
    payload = json.loads(Path(manifest_path).read_text())
    return [
        EnsembleMember(
            subset_name=m["subset_name"], model_type=m["model_type"], config_name=m["config_name"], threshold=m["threshold"],
            features=tuple(m["features"]), weight=m["weight"], backtest_sharpe=m["backtest_sharpe"], model_path=m["model_path"],
        )
        for m in payload["members"]
    ]


def predict_member(member: EnsembleMember, signals: pd.DataFrame) -> np.ndarray | None:
    """Returns this member's (1, 3) predicted class-probability row for the
    latest bar of `signals`, or None if its required features aren't
    computable this cycle (e.g. insufficient history)."""
    missing = [f for f in member.features if f not in signals.columns]
    if missing:
        return None
    latest = signals[list(member.features)].iloc[[-1]]
    if latest.isna().any(axis=None):
        return None
    fitted = load_model(member.model_type, Path(member.model_path))
    return predict_proba(fitted, latest)
