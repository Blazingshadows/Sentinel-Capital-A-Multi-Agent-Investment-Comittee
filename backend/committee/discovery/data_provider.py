"""Market-data adapter for Opportunity Discovery.

Implements `MarketDataPort` by reusing the existing `market_data` layer —
`prices.fetch_ohlcv` (Breeze + accumulating CSV cache). Sector comes from the
discovery universe asset (Breeze has no sector data), not a live call. Adds a
bounded, parallel, fault-tolerant batch fetch over the universe.

Heavy imports (`market_data`, which pulls `breeze_connect`) are lazy inside
methods, so importing the discovery package stays cheap and test-friendly. A
Breeze-backed provider is the only place the subsystem touches market data —
swapping the data source later touches nothing else.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from backend.committee.discovery.config import DiscoveryConfig

logger = logging.getLogger(__name__)


class LiveMarketDataProvider:
    """Production `MarketDataPort` backed by the Breeze-sourced market-data layer."""

    def __init__(self, config: DiscoveryConfig, sector_map: dict[str, str | None] | None = None) -> None:
        self._config = config
        self._sector_map = dict(sector_map or {})

    def get_ohlcv(self, symbol: str) -> pd.DataFrame | None:
        from backend.committee.market_data.prices import fetch_ohlcv

        try:
            df = fetch_ohlcv(symbol, period=self._config.data.period, interval=self._config.data.interval)
            if df is None or df.empty:
                return None
            return df
        except Exception:
            logger.warning("OHLCV fetch failed for %s — skipping this symbol.", symbol)
            return None

    def get_sector(self, symbol: str) -> str | None:
        return self._sector_map.get(symbol)

    def get_many_ohlcv(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        results: dict[str, pd.DataFrame] = {}
        workers = max(1, self._config.data.max_fetch_workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.get_ohlcv, sym): sym for sym in symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    df = future.result()
                except Exception:
                    logger.warning("OHLCV worker crashed for %s — skipping.", symbol)
                    df = None
                if df is not None and not df.empty:
                    results[symbol] = df
        logger.info("Batch OHLCV: %d/%d symbols resolved.", len(results), len(symbols))
        return results


class InMemoryDataProvider:
    """Deterministic `MarketDataPort` for tests / offline / replay. No network,
    no heavy imports."""

    def __init__(
        self,
        ohlcv_by_symbol: dict[str, pd.DataFrame],
        sector_by_symbol: dict[str, str | None] | None = None,
    ) -> None:
        self._ohlcv = dict(ohlcv_by_symbol)
        self._sectors = dict(sector_by_symbol or {})

    def get_ohlcv(self, symbol: str) -> pd.DataFrame | None:
        return self._ohlcv.get(symbol)

    def get_sector(self, symbol: str) -> str | None:
        return self._sectors.get(symbol)

    def get_many_ohlcv(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        return {s: self._ohlcv[s] for s in symbols if s in self._ohlcv}
