"""ICICI Direct Breeze API client -- replaces yfinance as the OHLCV source.
Only this module knows Breeze's request/response shape; callers (prices.py)
see the same DataFrame contract (Open/High/Low/Close/Volume, DatetimeIndex)
that the rest of the codebase already depends on.

Breeze quirks that shape this module:
- get_historical_data_v2 only supports "1second"/"1minute"/"5minute"/
  "30minute"/"1day" -- no 15-minute bucket, hence the project-wide move to
  5-minute bars (see config.FORECAST_TRAIN_INTERVAL).
- Max 1000 candles per request, so any wide date range has to be split into
  chunks and stitched back together.
- The session token is a daily, manually-generated api_session value (SEBI
  requires an actual browser login every trading day); there's no automated
  refresh, so a stale/missing token surfaces as BreezeAuthError with a
  pointer to re-auth, the same way forecasting.py degrades cleanly when its
  model file is missing rather than crashing the cycle.
"""

import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from backend.committee.config import BREEZE_STOCK_CODE_MAP, settings

if TYPE_CHECKING:
    from breeze_connect import BreezeConnect

EXCHANGE_CODE = "NSE"
MAX_CANDLES_PER_REQUEST = 1000
INTER_CHUNK_DELAY_SECONDS = 0.3  # polite pacing between paginated requests; tune against Breeze's documented rate limit

_INTERVAL_TO_BREEZE = {"1m": "1minute", "5m": "5minute", "30m": "30minute", "1d": "1day"}
_BAR_SECONDS = {"1m": 60, "5m": 300, "30m": 1800, "1d": 86400}

OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


class BreezeError(RuntimeError):
    """A Breeze API call failed (bad symbol, empty/error response, network issue)."""


class BreezeAuthError(BreezeError):
    """Breeze credentials are missing or the session token is invalid/expired."""


_client: "BreezeConnect | None" = None


def _get_client() -> "BreezeConnect":
    """Lazily authenticates and caches a single BreezeConnect session for
    the process lifetime -- mirrors forecasting.py's _model_cache pattern.
    Note: since the session token is only valid until midnight, a
    long-running process must be restarted after BREEZE_SESSION_TOKEN is
    refreshed in .env for the next trading day.

    The `breeze_connect` import itself is deferred to inside this function
    (not module level) because the package does a live network call
    (urlopen against its security-master URL) as a side effect of import --
    at module level, that made the whole API process crash on startup
    whenever the network hiccuped, even for endpoints that never touch
    market data. Deferring it means only the first actual Breeze call pays
    that cost, and a transient failure here degrades to BreezeAuthError
    like any other Breeze error instead of taking down the process.
    """
    global _client
    if _client is not None:
        return _client

    if not (settings.breeze_api_key and settings.breeze_api_secret and settings.breeze_session_token):
        raise BreezeAuthError(
            "Breeze credentials not configured. Set BREEZE_API_KEY and BREEZE_API_SECRET in .env "
            "(from https://api.icicidirect.com/apiuser/home), log in there to grab today's api_session, "
            "and set it as BREEZE_SESSION_TOKEN. It expires at midnight -- refresh it every trading day."
        )

    try:
        from breeze_connect import BreezeConnect
    except Exception as exc:
        raise BreezeAuthError(f"Failed to load breeze_connect (network issue at import time?): {exc}") from exc

    client = BreezeConnect(api_key=settings.breeze_api_key)
    try:
        client.generate_session(api_secret=settings.breeze_api_secret, session_token=settings.breeze_session_token)
    except Exception as exc:
        raise BreezeAuthError(
            f"Breeze session setup failed ({exc}) -- BREEZE_SESSION_TOKEN is likely expired or wrong; "
            "log in again and refresh it in .env."
        ) from exc

    _client = client
    return _client


def _stock_code(symbol: str) -> str:
    try:
        return BREEZE_STOCK_CODE_MAP[symbol]
    except KeyError:
        raise BreezeError(f"No Breeze stock_code mapping for {symbol!r} -- add it to config.BREEZE_STOCK_CODE_MAP.") from None


def _to_breeze_datetime(dt: datetime) -> str:
    # Breeze's own SDK builds timestamps as isoformat-to-the-second + ".000Z"
    # (see BreezeConnect's own current_date construction); note the "Z" is
    # reportedly cosmetic in practice (values are IST wall-clock, not true
    # UTC) -- verify against a live response before relying on this for
    # anything timezone-sensitive.
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".000Z"


def _normalize_candles(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime").sort_index()
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
    df = df[~df.index.duplicated(keep="last")]
    for col in OHLCV_COLUMNS:
        df[col] = pd.to_numeric(df[col])
    return df[OHLCV_COLUMNS]


def _raise_if_error(response, symbol: str, action: str) -> dict:
    if not isinstance(response, dict) or response.get("Error"):
        error = response.get("Error") if isinstance(response, dict) else response
        raise BreezeError(f"Breeze {action} failed for {symbol}: {error}")
    return response


def fetch_historical_ohlcv(symbol: str, from_date: datetime, to_date: datetime, interval: str = "5m") -> pd.DataFrame:
    """Pulls OHLCV for `symbol` between `from_date` and `to_date`, chunked
    into <=1000-candle windows (get_historical_data_v2's per-request cap)
    and stitched into one continuous, deduplicated DataFrame."""
    client = _get_client()
    stock_code = _stock_code(symbol)
    breeze_interval = _INTERVAL_TO_BREEZE[interval]
    chunk_span = timedelta(seconds=_BAR_SECONDS[interval] * MAX_CANDLES_PER_REQUEST)

    frames = []
    chunk_start = from_date
    first_chunk = True
    while chunk_start < to_date:
        if not first_chunk:
            time.sleep(INTER_CHUNK_DELAY_SECONDS)
        first_chunk = False

        chunk_end = min(chunk_start + chunk_span, to_date)
        response = client.get_historical_data_v2(
            interval=breeze_interval,
            from_date=_to_breeze_datetime(chunk_start),
            to_date=_to_breeze_datetime(chunk_end),
            stock_code=stock_code,
            exchange_code=EXCHANGE_CODE,
        )
        _raise_if_error(response, symbol, "get_historical_data_v2")
        frames.append(_normalize_candles(response.get("Success") or []))
        chunk_start = chunk_end

    if not frames:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    combined = pd.concat(frames)
    return combined[~combined.index.duplicated(keep="last")].sort_index()


def fetch_quote(symbol: str) -> dict:
    """Latest quote for `symbol`, e.g. for a real-time last-price check
    outside the historical pull."""
    client = _get_client()
    response = client.get_quotes(stock_code=_stock_code(symbol), exchange_code=EXCHANGE_CODE)
    _raise_if_error(response, symbol, "get_quotes")
    success = response.get("Success") or []
    return success[0] if success else {}
