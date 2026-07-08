"""Composition root + lightweight agent registry for Opportunity Discovery.

`build_default_discovery_agent(...)` is the single place the concrete
implementations are wired (Dependency Injection happens here, and only here).
It also loads the universe's sector map into the live data provider and
registers the universe's Breeze stock_codes so `prices.fetch_ohlcv` can
resolve universe symbols.
"""

from __future__ import annotations

from typing import Callable

from backend.committee.discovery.agent import OpportunityDiscoveryAgent
from backend.committee.discovery.config import DiscoveryConfig, load_config
from backend.committee.discovery.data_provider import LiveMarketDataProvider
from backend.committee.discovery.diversity import DiversityOptimizerAgent
from backend.committee.discovery.interfaces import MarketDataPort
from backend.committee.discovery.scanner import MarketScannerAgent
from backend.committee.discovery.scoring import OpportunityScoringAgent
from backend.committee.discovery.universe import load_sector_map, register_breeze_codes

DISCOVERY_AGENT_KEY = "opportunity_discovery"


def build_default_discovery_agent(
    config: DiscoveryConfig | None = None,
    data_provider: MarketDataPort | None = None,
    config_path: str | None = None,
) -> OpportunityDiscoveryAgent:
    cfg = config or load_config(config_path)
    if data_provider is None:
        register_breeze_codes()  # make universe symbols resolvable by prices.fetch_ohlcv
        data_provider = LiveMarketDataProvider(cfg, sector_map=load_sector_map())
    return OpportunityDiscoveryAgent(
        config=cfg,
        data_provider=data_provider,
        scanner=MarketScannerAgent(cfg),
        scorer=OpportunityScoringAgent(cfg),
        optimizer=DiversityOptimizerAgent(cfg),
    )


class AgentRegistry:
    """Instance-based registry mapping an agent key to a zero-arg factory."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], object]] = {}

    def register(self, key: str, factory: Callable[[], object]) -> None:
        if key in self._factories:
            raise ValueError(f"Agent key already registered: {key}")
        self._factories[key] = factory

    def create(self, key: str) -> object:
        if key not in self._factories:
            raise KeyError(f"No agent registered under key: {key}")
        return self._factories[key]()

    def keys(self) -> list[str]:
        return sorted(self._factories)


def default_registry(config_path: str | None = None) -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(DISCOVERY_AGENT_KEY, lambda: build_default_discovery_agent(config_path=config_path))
    return registry
