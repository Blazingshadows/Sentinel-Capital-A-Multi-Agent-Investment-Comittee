"""Tests for discovery config (deep-merge, fingerprint), the in-memory data
provider, and the Breeze-aware universe loader."""

import json

from backend.committee.discovery.config import DiscoveryConfig, load_config
from backend.committee.discovery.data_provider import InMemoryDataProvider
from backend.committee.discovery.universe import (
    load_breeze_codes,
    load_sector_map,
    load_universe,
    register_breeze_codes,
)
from backend.committee.tests.discovery_synth import make_ohlcv


def test_config_defaults_and_deep_merge(tmp_path):
    assert load_config(path="/nonexistent.json").diversity.target_min == 50
    override = {"diversity": {"target_max": 42}, "scoring": {"weights": {"momentum": 5.0}}}
    path = tmp_path / "o.json"; path.write_text(json.dumps(override))
    cfg = load_config(path=path)
    assert cfg.diversity.target_max == 42 and cfg.scoring.weights["momentum"] == 5.0
    assert cfg.diversity.target_min == 50 and cfg.scoring.weights["liquidity"] == 0.6  # siblings kept


def test_fingerprint_stable_and_sensitive():
    a, b = DiscoveryConfig(), DiscoveryConfig()
    assert a.fingerprint() == b.fingerprint()
    c = DiscoveryConfig(); c.diversity.target_max = 99
    assert c.fingerprint() != a.fingerprint()


def test_in_memory_provider():
    prov = InMemoryDataProvider({"AAA": make_ohlcv(seed=1)}, {"AAA": "IT"})
    assert prov.get_ohlcv("AAA") is not None
    assert prov.get_ohlcv("ZZZ") is None
    assert prov.get_sector("AAA") == "IT"
    assert set(prov.get_many_ohlcv(["AAA", "MISSING"])) == {"AAA"}


def test_universe_loads_sectors_and_codes():
    universe = load_universe()
    sectors = load_sector_map()
    codes = load_breeze_codes()
    assert len(universe) >= 200 and len(universe) == len(set(universe))
    assert sectors.get("RELIANCE") == "Energy & Oil Gas"
    assert codes.get("RELIANCE") == "RELIND"  # ships with the known watchlist mappings


def test_fetchable_only_restricts_to_mapped_symbols():
    fetchable = load_universe(fetchable_only=True)
    codes = load_breeze_codes()
    assert set(fetchable) == set(codes)  # only symbols with a Breeze stock_code


def test_register_breeze_codes_merges_into_config():
    from backend.committee.config import BREEZE_STOCK_CODE_MAP

    register_breeze_codes()
    for symbol, code in load_breeze_codes().items():
        assert BREEZE_STOCK_CODE_MAP.get(symbol) == code
