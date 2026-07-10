"""Regression test for a real bug found via a live demo run: restarting
Replay Mode rebuilds every `ReplayFeed` from the same starting cached bar
(see replay.player.ReplayFeed's cursor default), but the shared `Portfolio`
(app.state.portfolio) was never reset across runs. A position opened late in
one replay run got marked-to-market against a new run's very different
opening-bar price for the same symbol -- e.g. ADANIENT costed at ~3056 in one
run, then instantly "down" 30%+ against the next run's opening bar of ~2150,
a paper loss that never actually happened. Fixed by Portfolio.reset(), called
at the top of run_replay/run_replay_session before any bars are played."""

import asyncio

import pytest

from backend.committee.config import CAPITAL
from backend.committee.execution.portfolio import Portfolio
from backend.committee.replay import player as player_module
from backend.committee.tests.conftest import synthetic_ohlcv


def test_portfolio_reset_clears_stale_positions_and_cash():
    portfolio = Portfolio()
    portfolio.cash = 4_000.0
    portfolio.positions["ADANIENT"] = 2.0
    portfolio.entry_prices["ADANIENT"] = 3056.0

    portfolio.reset()

    assert portfolio.cash == pytest.approx(CAPITAL)
    assert portfolio.positions == {}
    assert portfolio.entry_prices == {}


def test_run_replay_session_resets_portfolio_before_playing_any_bars(monkeypatch):
    """A stale position/cost-basis from a previous run must be gone before
    this run's first tick, not just eventually washed out by trading."""
    portfolio = Portfolio()
    portfolio.cash = 4_000.0
    portfolio.positions["ADANIENT"] = 2.0
    portfolio.entry_prices["ADANIENT"] = 3056.0

    def fake_build_feed(symbol, interval):
        ohlcv = synthetic_ohlcv(n=60, start_price=2150.0)
        # cursor at the last bar -> has_next() is False, so the session's
        # while loop plays zero ticks; only the up-front reset is under test.
        return player_module.ReplayFeed(
            symbol=symbol, ohlcv=ohlcv, headlines=[], fundamentals={}, sector=None, cursor=len(ohlcv) - 1,
        )

    monkeypatch.setattr(player_module, "_build_feed", fake_build_feed)

    asyncio.run(
        player_module.run_replay_session(
            session_factory=lambda: (_ for _ in ()).throw(AssertionError("should not run any ticks")),
            portfolio=portfolio,
            watchlist=["ADANIENT"],
            use_discovery=False,
            max_bars=0,
        )
    )

    assert portfolio.cash == pytest.approx(CAPITAL)
    assert portfolio.positions == {}
    assert portfolio.entry_prices == {}
