"""Opportunity Discovery subsystem.

An **upstream, non-forecasting** stage that reduces the ~300-symbol NSE
universe to the ~50-60 highest-opportunity candidates the downstream
committee then reasons over. It never predicts prices, never emits BUY/SELL,
never forecasts returns — it only *selects the search space*.

    OpportunityDiscoveryAgent
        -> MarketScannerAgent      (liquidity/tradability/regime pre-screen, high recall)
        -> OpportunityScoringAgent (decorrelated, risk-adjusted multi-factor score)
        -> DiversityOptimizerAgent (sector + shrunk-correlation de-duplication, capacity-aware)
        -> list[OpportunityCandidate]

Composition root: `build_default_discovery_agent(...)`.
"""

from backend.committee.discovery.agent import OpportunityDiscoveryAgent
from backend.committee.discovery.config import DiscoveryConfig, load_config
from backend.committee.discovery.registry import (
    AgentRegistry,
    build_default_discovery_agent,
    default_registry,
)
from backend.committee.discovery.schemas import (
    DiscoveryResult,
    FactorScores,
    MarketRegime,
    OpportunityCandidate,
    ScanReport,
    SymbolScan,
)

__all__ = [
    "OpportunityDiscoveryAgent",
    "DiscoveryConfig",
    "load_config",
    "AgentRegistry",
    "build_default_discovery_agent",
    "default_registry",
    "DiscoveryResult",
    "FactorScores",
    "MarketRegime",
    "OpportunityCandidate",
    "ScanReport",
    "SymbolScan",
]
