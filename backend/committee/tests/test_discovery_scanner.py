"""Tests for the Market Scanner: high-recall gates, new metric population,
regime branches, and cross-sectional dispersion."""

from backend.committee.discovery.config import load_config
from backend.committee.discovery.scanner import MarketScannerAgent
from backend.committee.discovery.schemas import MarketRegime, RejectReason
from backend.committee.tests.discovery_synth import make_ohlcv, make_universe


def _scanner():
    return MarketScannerAgent(load_config())


def test_passes_liquid_symbol_and_populates_new_metrics():
    ohlcv = {"GOOD": make_ohlcv(base=1000, volume=60_000, drift=0.001, seed=3)}
    scans, report = _scanner().scan(ohlcv, {"GOOD": "IT"})
    s = scans[0]
    assert s.passed and s.reject_reason is None
    assert s.vol_expansion_ratio > 0 and s.trend_efficiency >= 0
    assert s.risk_adj_momentum != 0.0
    assert report.passed == 1


def test_rejects_penny_illiquid_short():
    ohlcv = {
        "PENNY": make_ohlcv(base=2.0, volume=60_000, seed=4),
        "ILLIQ": make_ohlcv(base=1000, volume=1.0, seed=5),
        "SHORT": make_ohlcv(base=1000, volume=60_000, n=20, seed=6),
    }
    scans, _ = _scanner().scan(ohlcv, {k: None for k in ohlcv})
    by = {s.symbol: s for s in scans}
    assert by["PENNY"].reject_reason == RejectReason.UNTRADEABLE_PRICE
    assert by["ILLIQ"].reject_reason == RejectReason.ILLIQUID
    assert by["SHORT"].reject_reason == RejectReason.INSUFFICIENT_HISTORY


def test_high_recall_keeps_most_of_a_liquid_universe():
    ohlcv, sectors = make_universe(60)
    _, report = _scanner().scan(ohlcv, sectors)
    assert report.passed >= int(0.8 * report.scanned)
    assert report.cross_sectional_dispersion >= 0.0


def test_regime_branches():
    up = {f"U{i}": make_ohlcv(base=500 + i, drift=0.004, vol=0.003, seed=100 + i) for i in range(15)}
    down = {f"D{i}": make_ohlcv(base=500 + i, drift=-0.004, vol=0.003, seed=200 + i) for i in range(15)}
    hv = {f"H{i}": make_ohlcv(base=500 + i, drift=0.0, vol=0.03, seed=300 + i) for i in range(15)}
    mixed = {f"M{i}": make_ohlcv(base=500 + i, drift=0.004 if i % 2 else -0.004, vol=0.003, seed=400 + i) for i in range(16)}

    assert _scanner().scan(up, {k: "IT" for k in up})[1].regime == MarketRegime.RISK_ON
    assert _scanner().scan(down, {k: "Bank" for k in down})[1].regime == MarketRegime.RISK_OFF
    assert _scanner().scan(hv, {k: "Energy" for k in hv})[1].regime == MarketRegime.HIGH_VOLATILITY
    assert _scanner().scan(mixed, {k: "Auto" for k in mixed})[1].regime == MarketRegime.NEUTRAL


def test_regime_unknown_when_nothing_survives():
    ohlcv = {f"P{i}": make_ohlcv(base=1.0, seed=500 + i) for i in range(5)}
    _, report = _scanner().scan(ohlcv, {k: None for k in ohlcv})
    assert report.passed == 0 and report.regime == MarketRegime.UNKNOWN
