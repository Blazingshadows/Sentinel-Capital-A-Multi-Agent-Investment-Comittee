"""Manual-mode suggestion flow (orchestration.loop.run_watchlist_once with
execution_mode="manual"): actionable decisions defer to a pending
schemas.Suggestion instead of auto-executing, get superseded (not expired)
by that symbol's own next cycle, and HOLD decisions still finalize
immediately in both modes. Agent evaluation itself is monkeypatched so
these run fast and deterministically, without real LLM/market-data calls --
the thing under test is the branching in run_watchlist_once, not the
committee's directional reasoning."""

from backend.committee.execution.portfolio import Portfolio
from backend.committee.market_data.context import MarketContext
from backend.committee.orchestration import cycle as cycle_module
from backend.committee.orchestration import loop as loop_module
from backend.committee.schemas import (
    ConsensusDecision,
    Decision,
    DebateResult,
    RiskAction,
    RiskVerdict,
)
from backend.committee.tests.conftest import synthetic_ohlcv


def _consensus(symbol: str, decision: Decision, allocation: float = 0.0) -> ConsensusDecision:
    return ConsensusDecision(
        symbol=symbol,
        decision=decision,
        confidence=0.8,
        allocation=allocation,
        reasoning="test",
        influence_breakdown=[],
        debate=DebateResult(original_recommendations=[], contrarian_challenge="", revised_recommendations=[]),
    )


def _risk(action: RiskAction, allocation: float) -> RiskVerdict:
    return RiskVerdict(action=action, approved_allocation=allocation, volatility_estimate=0.02, reason="test")


def _patch_pipeline(monkeypatch, contexts: dict[str, MarketContext], decisions: dict[str, tuple]) -> None:
    def fake_build_context(symbol, **kwargs):
        return contexts[symbol]

    def fake_evaluate_context(session, context, cycle_ts, current_position=0.0):
        consensus, risk_verdict = decisions[context.symbol]
        return consensus, risk_verdict, []

    monkeypatch.setattr(loop_module, "build_context", fake_build_context)
    monkeypatch.setattr(loop_module, "evaluate_context", fake_evaluate_context)


def test_manual_mode_defers_actionable_and_finalizes_hold(db_session, monkeypatch):
    contexts = {
        "FAKEBUY": MarketContext(symbol="FAKEBUY", ohlcv=synthetic_ohlcv(start_price=100.0), headlines=[], fundamentals={}, sector=None),
        "FAKEHOLD": MarketContext(symbol="FAKEHOLD", ohlcv=synthetic_ohlcv(start_price=200.0), headlines=[], fundamentals={}, sector=None),
    }
    decisions = {
        "FAKEBUY": (_consensus("FAKEBUY", Decision.BUY, 0.1), _risk(RiskAction.APPROVE, 0.1)),
        "FAKEHOLD": (_consensus("FAKEHOLD", Decision.HOLD, 0.0), _risk(RiskAction.APPROVE, 0.0)),
    }
    _patch_pipeline(monkeypatch, contexts, decisions)

    portfolio = Portfolio()
    suggestions: dict = {}
    logs = loop_module.run_watchlist_once(
        db_session, portfolio, watchlist=["FAKEBUY", "FAKEHOLD"],
        execution_mode="manual", suggestions=suggestions,
    )

    assert "FAKEBUY" in suggestions
    assert "FAKEHOLD" not in suggestions
    assert suggestions["FAKEBUY"].consensus.decision == Decision.BUY
    assert suggestions["FAKEBUY"].suggested_price == contexts["FAKEBUY"].latest_price

    logged_symbols = {log.stock for log in logs}
    assert "FAKEHOLD" in logged_symbols  # HOLD finalizes immediately, no suggestion needed
    assert "FAKEBUY" not in logged_symbols  # BUY deferred, not executed this cycle

    # No capital committed for the deferred BUY -- only a suggestion exists.
    assert portfolio.positions.get("FAKEBUY", 0.0) == 0.0


def test_next_cycle_supersedes_a_pending_suggestion(db_session, monkeypatch):
    context = MarketContext(symbol="FAKEBUY", ohlcv=synthetic_ohlcv(start_price=100.0), headlines=[], fundamentals={}, sector=None)
    contexts = {"FAKEBUY": context}
    portfolio = Portfolio()
    suggestions: dict = {}

    # Cycle 1: BUY -> creates a pending suggestion.
    _patch_pipeline(monkeypatch, contexts, {"FAKEBUY": (_consensus("FAKEBUY", Decision.BUY, 0.1), _risk(RiskAction.APPROVE, 0.1))})
    loop_module.run_watchlist_once(db_session, portfolio, watchlist=["FAKEBUY"], execution_mode="manual", suggestions=suggestions)
    assert "FAKEBUY" in suggestions

    # Cycle 2: same symbol now evaluates to HOLD -> the stale BUY suggestion
    # must be cleared, not left sitting there executable against a decision
    # the committee has already moved off of.
    _patch_pipeline(monkeypatch, contexts, {"FAKEBUY": (_consensus("FAKEBUY", Decision.HOLD, 0.0), _risk(RiskAction.APPROVE, 0.0))})
    loop_module.run_watchlist_once(db_session, portfolio, watchlist=["FAKEBUY"], execution_mode="manual", suggestions=suggestions)
    assert "FAKEBUY" not in suggestions


def test_executing_a_suggestion_uses_the_fresh_price_not_the_suggested_price(db_session, monkeypatch):
    suggested_context = MarketContext(symbol="FAKEBUY", ohlcv=synthetic_ohlcv(start_price=100.0), headlines=[], fundamentals={}, sector=None)
    contexts = {"FAKEBUY": suggested_context}
    decisions = {"FAKEBUY": (_consensus("FAKEBUY", Decision.BUY, 0.1), _risk(RiskAction.APPROVE, 0.1))}
    _patch_pipeline(monkeypatch, contexts, decisions)

    portfolio = Portfolio()
    suggestions: dict = {}
    loop_module.run_watchlist_once(db_session, portfolio, watchlist=["FAKEBUY"], execution_mode="manual", suggestions=suggestions)
    suggestion = suggestions["FAKEBUY"]
    suggested_price = suggestion.suggested_price
    assert portfolio.positions.get("FAKEBUY", 0.0) == 0.0  # nothing executed yet

    # Simulate api.main's /suggestions/{symbol}/execute: a fresh context at
    # a different (here: higher) price than what was suggested.
    fresh_context = MarketContext(symbol="FAKEBUY", ohlcv=synthetic_ohlcv(start_price=130.0, seed=99), headlines=[], fundamentals={}, sector=None)
    fresh_price = fresh_context.latest_price
    assert fresh_price != suggested_price

    from datetime import datetime, timezone

    log = cycle_module.finalize_cycle(
        db_session, portfolio, fresh_context, suggestion.consensus, suggestion.risk_verdict,
        suggestion.revised_recommendations, datetime.now(timezone.utc),
    )

    assert log.trade.price == fresh_price
    assert log.trade.price != suggested_price
    assert portfolio.positions.get("FAKEBUY", 0.0) != 0.0  # the trade actually landed
