"""End-to-end tests for the OpportunityDiscoveryAgent and orchestration glue."""

import json

from backend.committee.discovery.config import load_config
from backend.committee.discovery.data_provider import InMemoryDataProvider
from backend.committee.discovery.registry import build_default_discovery_agent
from backend.committee.discovery.schemas import DiscoveryResult
from backend.committee.orchestration.discovery_cycle import resolve_watchlist
from backend.committee.tests.discovery_synth import make_universe


def _agent(n_symbols=90):
    ohlcv, sectors = make_universe(n_symbols)
    provider = InMemoryDataProvider(ohlcv, sectors)
    return build_default_discovery_agent(config=load_config(), data_provider=provider), list(ohlcv.keys())


def test_discover_reduces_to_target_band():
    agent, universe = _agent(90)
    r = agent.discover(universe)
    assert isinstance(r, DiscoveryResult)
    assert r.universe_size == len(universe)
    assert 50 <= r.selected_count <= 60
    assert r.selected_count == len(r.candidates)


def test_output_explainable_and_json_serializable():
    agent, universe = _agent(80)
    r = agent.discover(universe)
    payload = json.loads(r.model_dump_json())
    assert {"candidates", "regime", "scan_report", "config_fingerprint"}.issubset(payload)
    top = r.candidates[0]
    assert top.rank == 1 and top.theme and top.reasoning and top.selection_explanation
    assert top.contribution_pct and top.confidence_breakdown
    assert 0.0 <= top.confidence <= 1.0 and 0.0 <= top.capacity_score <= 1.0


def test_deterministic():
    agent, universe = _agent(80)
    assert agent.discover(universe).selected_symbols == agent.discover(universe).selected_symbols


def test_never_predicts_direction():
    agent, universe = _agent(70)
    r = agent.discover(universe)
    forbidden = {"decision", "buy", "sell", "signal", "prediction", "forecast", "target_price", "expected_return"}
    for c in r.candidates:
        assert forbidden.isdisjoint(c.model_dump().keys())


def test_resolve_watchlist_unions_holdings_and_falls_back():
    agent, universe = _agent(70)
    r = agent.discover(universe)
    wl = resolve_watchlist(r, held_positions=["HELD1"], fallback=["FB"])
    assert "HELD1" in wl and set(r.selected_symbols).issubset(set(wl))
    assert resolve_watchlist(None, held_positions=["HELD1"], fallback=["FB", "FB"]) == ["FB", "HELD1"]
