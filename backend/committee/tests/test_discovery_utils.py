"""Tests for shared discovery utilities, incl. the soft-winsor standardization
that preserves tail ordering (the false-negative fix)."""

import numpy as np
import pandas as pd

from backend.committee.discovery.utils import (
    dedupe_preserve_order,
    finite_float,
    percentile_rank,
    robust_standardize,
)


def test_dedupe_preserves_first_seen_order():
    assert dedupe_preserve_order(["B", "A", "B", "C", "A"]) == ["B", "A", "C"]
    assert dedupe_preserve_order([]) == []


def test_finite_float_coerces_non_finite_to_zero():
    assert finite_float(3.5) == 3.5
    assert finite_float(np.nan) == 0.0
    assert finite_float(np.inf) == 0.0


def test_soft_winsor_preserves_tail_ordering():
    """Two extreme movers: hard-clip ties them at the cap (destroying the
    signal discovery exists to find); tanh keeps their order."""
    # Two values far enough into the tail that hard-clip clamps both to +3.
    series = pd.Series([0.0, 1.0, 2.0, 20.0, 40.0], index=list("abcde"))
    clipped = robust_standardize(series, winsor_z=3.0, eps=1e-9, method="clip")
    softened = robust_standardize(series, winsor_z=3.0, eps=1e-9, method="tanh")

    assert clipped["d"] == clipped["e"]  # both clamped to +3 -> tied
    assert softened["e"] > softened["d"]  # ordering survives
    assert softened.abs().max() <= 3.0 + 1e-9  # still bounded


def test_robust_standardize_zero_when_no_dispersion():
    flat = pd.Series([7.0] * 10)
    assert (robust_standardize(flat, 3.0, 1e-9) == 0.0).all()


def test_percentile_rank_is_monotone_and_bounded():
    s = pd.Series([10.0, 20.0, 30.0, 40.0])
    pr = percentile_rank(s)
    assert list(pr) == sorted(pr)
    assert pr.max() == 100.0 and pr.min() > 0.0
