"""Abstract ports for the Opportunity Discovery subsystem (Dependency
Inversion + Interface Segregation). Concrete stages depend on these narrow
contracts; the orchestrating agent depends only on the abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

import pandas as pd

from backend.committee.discovery.config import DiscoveryConfig
from backend.committee.discovery.schemas import OpportunityCandidate, ScanReport, SymbolScan


@runtime_checkable
class MarketDataPort(Protocol):
    """Read-only market-data access. A structural Protocol so any object with
    these methods qualifies — the production adapter wraps the existing
    `market_data` layer (Breeze), tests pass an in-memory object."""

    def get_ohlcv(self, symbol: str) -> pd.DataFrame | None:
        """OHLCV (Open/High/Low/Close/Volume) for `symbol`, or None. Must never
        raise for a single bad symbol."""
        ...

    def get_sector(self, symbol: str) -> str | None:
        ...

    def get_many_ohlcv(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        """Batch fetch; returns only the symbols that resolved to data."""
        ...


class AbstractMarketScanner(ABC):
    """Stage 1: raw universe -> tradeable survivors + metric bundle + regime."""

    @abstractmethod
    def scan(
        self, ohlcv_by_symbol: dict[str, pd.DataFrame], sector_by_symbol: dict[str, str | None]
    ) -> tuple[list[SymbolScan], ScanReport]:
        ...


class AbstractOpportunityScorer(ABC):
    """Stage 2: survivors -> scored, explained candidates (cross-sectional)."""

    @abstractmethod
    def score(self, scans: list[SymbolScan], report: ScanReport) -> list[OpportunityCandidate]:
        ...


class AbstractDiversityOptimizer(ABC):
    """Stage 3: de-duplicate scored candidates down to the target count."""

    @abstractmethod
    def optimize(
        self,
        candidates: list[OpportunityCandidate],
        returns_by_symbol: dict[str, pd.Series] | None = None,
    ) -> list[OpportunityCandidate]:
        ...


class ConfigAware:
    """Constructor-injection base: every stage is built with the shared,
    immutable `DiscoveryConfig` (no globals)."""

    def __init__(self, config: DiscoveryConfig) -> None:
        self._config = config

    @property
    def config(self) -> DiscoveryConfig:
        return self._config
