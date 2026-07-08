"""Orchestration glue between Opportunity Discovery and the committee.

Discovery runs on its own (slower) cadence and turns its result into the
concrete `watchlist` that `orchestration.loop.run_watchlist_once` already
accepts, so the committee's internals are untouched. Invariants: never drop a
held position; always fall back to `config.WATCHLIST` when discovery is empty.
"""

from __future__ import annotations

import logging

from backend.committee.config import WATCHLIST
from backend.committee.discovery.agent import OpportunityDiscoveryAgent
from backend.committee.discovery.registry import build_default_discovery_agent
from backend.committee.discovery.schemas import DiscoveryResult
from backend.committee.discovery.utils import dedupe_preserve_order

logger = logging.getLogger(__name__)


def run_discovery_once(
    agent: OpportunityDiscoveryAgent | None = None,
    universe: list[str] | None = None,
    config_path: str | None = None,
) -> DiscoveryResult:
    discovery_agent = agent or build_default_discovery_agent(config_path=config_path)
    return discovery_agent.discover(universe)


def resolve_watchlist(
    result: DiscoveryResult | None,
    held_positions: list[str] | None = None,
    fallback: list[str] | None = None,
) -> list[str]:
    held = list(held_positions or [])
    base_fallback = list(fallback if fallback is not None else WATCHLIST)
    if result is None or not result.selected_symbols:
        logger.warning("Discovery produced no candidates — using fallback watchlist.")
        return dedupe_preserve_order(base_fallback + held)
    return dedupe_preserve_order(result.selected_symbols + held)
