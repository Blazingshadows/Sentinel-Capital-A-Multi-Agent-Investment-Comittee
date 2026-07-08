"""Deterministic synthetic-universe builders for Opportunity Discovery tests.
Not collected by pytest (no `test_` prefix). Seeded — no network, no Breeze."""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_ohlcv(*, n: int = 120, base: float = 1000.0, drift: float = 0.0004,
               vol: float = 0.004, volume: float = 50_000.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(drift, vol, n)
    closes = base * np.cumprod(1 + returns)
    index = pd.date_range("2026-01-01 09:15", periods=n, freq="5min")
    vol_series = volume * (1 + rng.normal(0, 0.25, n)).clip(0.1)
    return pd.DataFrame(
        {"Open": closes, "High": closes * (1 + abs(vol)), "Low": closes * (1 - abs(vol)),
         "Close": closes, "Volume": vol_series},
        index=index,
    )


def make_universe(
    n_symbols: int = 60,
    sectors: tuple[str, ...] = ("IT", "Bank", "Auto", "Pharma", "Energy", "FMCG"),
) -> tuple[dict[str, pd.DataFrame], dict[str, str | None]]:
    ohlcv: dict[str, pd.DataFrame] = {}
    sector_map: dict[str, str | None] = {}
    for i in range(n_symbols):
        sym = f"STK{i:03d}"
        ohlcv[sym] = make_ohlcv(
            base=50.0 + i * 7.0,
            drift=(i % 7 - 3) * 0.0004,
            vol=0.003 + 0.004 * ((i % 5) / 5.0),
            volume=30_000.0 + i * 800.0,
            seed=i,
        )
        sector_map[sym] = sectors[i % len(sectors)]
    return ohlcv, sector_map
