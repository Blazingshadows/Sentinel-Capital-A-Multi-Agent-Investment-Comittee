import datetime as dt

import pandas as pd
import pytest

from backend.committee.market_data import breeze_client


def test_normalize_candles_maps_breeze_schema_to_ohlcv_contract():
    rows = [
        {"close": 100.5, "datetime": "2026-01-05 09:15:00", "exchange_code": "NSE",
         "high": 101.0, "low": 100.0, "open": 100.2, "stock_code": "RELIND", "volume": "5000"},
        {"close": 101.0, "datetime": "2026-01-05 09:20:00", "exchange_code": "NSE",
         "high": 101.5, "low": 100.5, "open": 100.5, "stock_code": "RELIND", "volume": "6000"},
    ]
    df = breeze_client._normalize_candles(rows)
    assert list(df.columns) == breeze_client.OHLCV_COLUMNS
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.is_monotonic_increasing
    assert df["Volume"].tolist() == [5000, 6000]  # Breeze sometimes returns numeric fields as strings


def test_normalize_candles_empty_rows_returns_empty_frame_with_columns():
    df = breeze_client._normalize_candles([])
    assert df.empty
    assert list(df.columns) == breeze_client.OHLCV_COLUMNS


def test_fetch_historical_ohlcv_raises_without_credentials(monkeypatch):
    monkeypatch.setattr(breeze_client, "_client", None)
    monkeypatch.setattr(breeze_client.settings, "breeze_api_key", "")
    monkeypatch.setattr(breeze_client.settings, "breeze_api_secret", "")
    monkeypatch.setattr(breeze_client.settings, "breeze_session_token", "")

    with pytest.raises(breeze_client.BreezeAuthError):
        breeze_client.fetch_historical_ohlcv("RELIANCE", dt.datetime(2026, 1, 1), dt.datetime(2026, 1, 2))


class _FakeBreezeClient:
    def __init__(self, rows_per_call):
        self.rows_per_call = rows_per_call
        self.calls = 0

    def get_historical_data_v2(self, **kwargs):
        row = self.rows_per_call[self.calls]
        self.calls += 1
        return {"Error": None, "Status": 200, "Success": [row]}


def test_fetch_historical_ohlcv_paginates_and_stitches_chunks(monkeypatch):
    """get_historical_data_v2 caps out at 1000 candles/request; a wide date
    range must be split into multiple chunked calls and stitched back into
    one continuous, sorted DataFrame."""
    rows = [
        {"open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000, "datetime": "2026-01-01 09:15:00"},
        {"open": 101, "high": 102, "low": 100, "close": 101.5, "volume": 1100, "datetime": "2026-01-01 09:16:00"},
        {"open": 102, "high": 103, "low": 101, "close": 102.5, "volume": 1200, "datetime": "2026-01-01 09:17:00"},
    ]
    fake_client = _FakeBreezeClient(rows)
    monkeypatch.setattr(breeze_client, "_get_client", lambda: fake_client)
    monkeypatch.setattr(breeze_client, "MAX_CANDLES_PER_REQUEST", 1)  # force one candle per chunk
    monkeypatch.setattr(breeze_client, "INTER_CHUNK_DELAY_SECONDS", 0)

    from_date = dt.datetime(2026, 1, 1, 9, 15)
    to_date = dt.datetime(2026, 1, 1, 9, 18)
    result = breeze_client.fetch_historical_ohlcv("RELIANCE", from_date, to_date, interval="1m")

    assert fake_client.calls == 3
    assert len(result) == 3
    assert result.index.is_monotonic_increasing
    assert result["Close"].tolist() == [100.5, 101.5, 102.5]
