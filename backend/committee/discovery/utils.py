"""Small, pure, dependency-light helpers shared across the discovery
subsystem (dedupe, finite-float coercion, robust cross-sectional
standardization, percentile ranking)."""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


def dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    """De-duplicate while preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def finite_float(value) -> float:
    """Coerce to a finite float (0.0 for NaN/inf) — keeps JSON payloads clean
    and Pydantic-safe."""
    result = float(value)
    return result if np.isfinite(result) else 0.0


def robust_standardize(series: pd.Series, winsor_z: float, eps: float, method: str = "tanh") -> pd.Series:
    """Cross-sectional robust standardization: (x - median) / (1.4826 * MAD),
    tail-controlled by `method`:

    * ``"tanh"`` — soft-winsor ``winsor_z * tanh(z / winsor_z)``. Squashes
      extremes smoothly but **preserves their ordering** (a +8σ name stays
      above a +5σ one). Preferred for opportunity discovery, where the tails
      are exactly the signal and hard-clipping would tie the biggest movers.
    * ``"clip"`` — hard winsorization to ``[-winsor_z, +winsor_z]``.

    Returns all-zeros when the cross-section has no dispersion (MAD ~ 0), i.e.
    the factor carries no discriminating information this cycle.
    """
    numeric = series.astype(float)
    median = numeric.median()
    mad = (numeric - median).abs().median()
    scale = 1.4826 * mad
    if not np.isfinite(scale) or scale < eps:
        return pd.Series(0.0, index=series.index)
    z = ((numeric - median) / scale).fillna(0.0)
    if method == "clip":
        return z.clip(-winsor_z, winsor_z)
    return winsor_z * np.tanh(z / winsor_z)


def percentile_rank(series: pd.Series) -> pd.Series:
    """Cross-sectional percentile in (0, 100]. Robust to outliers (unlike
    min-max, which one extreme value squashes) and directly interpretable
    ("this name is in the Nth percentile of opportunity today")."""
    if series.empty:
        return series
    return series.rank(pct=True) * 100.0
