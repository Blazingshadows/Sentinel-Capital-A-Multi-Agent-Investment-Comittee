"""Builds the full signal matrix from `backend.committee.signals.SIGNAL_REGISTRY`
and the candidate feature subsets `search.py` trains a model per."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backend.committee.config import ALGO_RANDOM_SUBSET_COUNT, ALGO_RANDOM_SUBSET_FRACTION, ALGO_SEED
from backend.committee.signals import SIGNAL_REGISTRY, STYLES


def build_all_signals(ohlcv: pd.DataFrame, symbol: str | None = None, panel: pd.DataFrame | None = None) -> pd.DataFrame:
    """One column per registered signal, aligned to `ohlcv.index`.
    Cross-sectional signals (`SignalSpec.needs_panel`) come back all-NaN if
    `symbol`/`panel` aren't supplied -- they'll simply drop out of any
    feature subset via the caller's `.dropna()`, same as any other agent
    degrading gracefully to insufficient data.
    """
    columns: dict[str, pd.Series] = {}
    for spec in SIGNAL_REGISTRY.values():
        if spec.needs_panel:
            if symbol is None or panel is None:
                columns[spec.name] = pd.Series(float("nan"), index=ohlcv.index)
                continue
            columns[spec.name] = spec.fn(ohlcv, symbol=symbol, panel=panel, **spec.params)
        else:
            columns[spec.name] = spec.fn(ohlcv, **spec.params)
    return pd.DataFrame(columns, index=ohlcv.index)


@dataclass(frozen=True)
class FeatureSubset:
    name: str
    features: tuple[str, ...]


def iter_feature_subsets(
    random_count: int = ALGO_RANDOM_SUBSET_COUNT,
    random_fraction: float = ALGO_RANDOM_SUBSET_FRACTION,
    seed: int = ALGO_SEED,
) -> list[FeatureSubset]:
    """One subset per style (the "pure strategy style" candidates), one
    all-combined subset, and `random_count` random subsets -- a bounded
    search over feature combinations instead of the infeasible full power
    set. Deterministic given `seed` so a search run is reproducible.
    """
    all_names = sorted(SIGNAL_REGISTRY)
    subsets = [FeatureSubset(name=f"style_{style}", features=tuple(sorted(n for n, s in SIGNAL_REGISTRY.items() if s.style == style)))
               for style in STYLES]
    subsets.append(FeatureSubset(name="all_combined", features=tuple(all_names)))

    rng = np.random.default_rng(seed)
    subset_size = max(2, round(len(all_names) * random_fraction))
    for i in range(random_count):
        chosen = tuple(sorted(rng.choice(all_names, size=subset_size, replace=False)))
        subsets.append(FeatureSubset(name=f"random_{i}", features=chosen))

    return subsets
