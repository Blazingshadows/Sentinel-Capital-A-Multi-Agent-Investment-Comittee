import pandas as pd

from backend.committee.market_data import prices


def _fake_ohlcv(days: list[str], closes: list[float]) -> pd.DataFrame:
    idx = pd.to_datetime(days)
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [1000] * len(days)},
        index=idx,
    )


def test_fetch_ohlcv_accumulates_across_calls_instead_of_overwriting(tmp_path, monkeypatch):
    """Breeze's per-request candle cap means a single call's window is not a
    ceiling on the cache -- repeated calls over time should grow the
    effective history rather than each call discarding what came before."""
    monkeypatch.setattr(prices, "DATA_DIR", tmp_path)

    first_days = ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]
    first_closes = [100, 101, 102, 103, 104]
    monkeypatch.setattr(prices.breeze_client, "fetch_historical_ohlcv", lambda *a, **k: _fake_ohlcv(first_days, first_closes))
    result1 = prices.fetch_ohlcv("TEST", period="60d", interval="1d")
    assert len(result1) == 5

    # A later call's window overlaps days 4-5 and extends to day 8; the
    # overlapping days carry different (corrected) values.
    second_days = ["2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    second_closes = [999, 999, 105, 106, 107]
    monkeypatch.setattr(prices.breeze_client, "fetch_historical_ohlcv", lambda *a, **k: _fake_ohlcv(second_days, second_closes))
    result2 = prices.fetch_ohlcv("TEST", period="60d", interval="1d")

    assert len(result2) == 8  # accumulated (1-8), not replaced (would be 5)
    assert result2.loc["2026-01-01", "Close"] == 100  # preserved from the first call
    assert result2.loc["2026-01-04", "Close"] == 999  # newer fetch wins on overlap
    assert result2.loc["2026-01-08", "Close"] == 107  # new day appended
