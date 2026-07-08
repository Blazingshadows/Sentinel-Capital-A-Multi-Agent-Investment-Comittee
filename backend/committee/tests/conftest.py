import numpy as np
import pandas as pd
import pytest

from backend.committee.market_data.context import MarketContext
from backend.committee.persistence.db import init_db, make_engine, make_session_factory


def synthetic_ohlcv(n: int = 100, start_price: float = 1500.0, drift: float = 0.0005,
                     vol: float = 0.004, seed: int = 42) -> pd.DataFrame:
    """Deterministic (seeded) synthetic OHLCV series so tests never depend on
    live market data or network access."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(drift, vol, n)
    closes = start_price * np.cumprod(1 + returns)
    index = pd.date_range("2026-01-01 09:15", periods=n, freq="15min")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.001,
            "Low": closes * 0.999,
            "Close": closes,
            "Volume": 10_000,
        },
        index=index,
    )


@pytest.fixture
def db_session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session = make_session_factory(engine)()
    yield session
    session.close()


@pytest.fixture
def synthetic_context() -> MarketContext:
    return MarketContext(
        symbol="INFY",
        ohlcv=synthetic_ohlcv(),
        headlines=["Infosys beats Q1 earnings estimates"],
        fundamentals={},
        sector="IT",
        context_flags=["earnings_day"],
    )
