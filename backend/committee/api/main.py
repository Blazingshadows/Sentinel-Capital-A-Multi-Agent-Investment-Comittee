"""FastAPI surface — README's API/dashboard layer. Exposes the ability to
trigger committee cycles and read back the audit trail (decisions, trades,
portfolio curve) that every other layer already writes to SQLite. Building
the dashboard UI itself is out of scope for this pass; this is what it would
consume.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.committee.audit.report import cost_breakdown_by_symbol, summarize_pnl
from backend.committee.config import BUYING_POWER, CAPITAL, LEVERAGE
from backend.committee.execution.portfolio import Portfolio
from backend.committee.market_data.context import build_context
from backend.committee.orchestration.cycle import finalize_cycle, run_cycle
from backend.committee.orchestration.loop import run_watchlist_once, square_off_all_positions
from backend.committee.persistence import repository
from backend.committee.persistence.db import init_db, make_engine, make_session_factory
from backend.committee.replay.player import run_replay_session

EXECUTION_MODES = {"autonomous", "manual"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = make_engine()
    init_db(engine)
    app.state.session_factory = make_session_factory(engine)
    app.state.portfolio = Portfolio()
    app.state.discovery_agent = None  # built lazily on first /discovery call
    app.state.last_discovery = None
    # Single shared dict a running watchlist/replay pass mutates in place
    # (see loop.run_watchlist_once's `progress` param) and /session/progress
    # reads back -- `busy` guards against two passes racing on the same
    # `app.state.portfolio` at once, since only one dashboard session runs
    # at a time.
    app.state.progress = {"phase": "idle", "mode": None, "detail": "Idle."}
    app.state.busy = False
    # Manual-mode pending suggestions (see loop.run_watchlist_once and
    # schemas.Suggestion), keyed by symbol -- a symbol's next cycle
    # overwrites its own entry, and /suggestions/{symbol}/execute removes it.
    app.state.suggestions = {}
    yield


def _get_discovery_agent(app: FastAPI):
    """Lazily build and cache the Opportunity Discovery agent so importing the
    API never pulls the discovery data path unless it's actually used."""
    if app.state.discovery_agent is None:
        from backend.committee.discovery.registry import build_default_discovery_agent

        app.state.discovery_agent = build_default_discovery_agent()
    return app.state.discovery_agent


app = FastAPI(title="Autonomous Multi-Agent Investment Committee", lifespan=lifespan)

# Dashboard runs on the Vite dev server (a different origin/port) during
# development; loosest-that's-still-scoped since this never leaves localhost.
# Regex (not a fixed port) because Vite silently bumps to 5174/5175/... when
# 5173 is already taken by another dev server instance.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


def _decision_to_dict(row) -> dict:
    return {
        "id": row.id,
        "cycle_ts": row.cycle_ts,
        "stock": row.stock,
        "agent_recommendations": row.agent_recommendations,
        "debate": row.debate,
        "influence_breakdown": row.influence_breakdown,
        "consensus_decision": row.consensus_decision,
        "consensus_confidence": row.consensus_confidence,
        "consensus_allocation": row.consensus_allocation,
        "consensus_reasoning": row.consensus_reasoning,
        "risk_action": row.risk_action,
        "risk_approved_allocation": row.risk_approved_allocation,
        "risk_volatility_estimate": row.risk_volatility_estimate,
        "risk_reason": row.risk_reason,
        "risk_expected_return": row.risk_expected_return,
        "risk_expected_drawdown": row.risk_expected_drawdown,
        "alternatives": row.alternatives or [],
        "action_taken": row.action_taken,
        "qty": row.qty,
        "price": row.price,
        "cost_breakdown": row.cost_breakdown,
        "net_cash_flow": row.net_cash_flow,
    }


def _trade_to_dict(row) -> dict:
    return {
        "id": row.id,
        "ts": row.ts,
        "stock": row.stock,
        "action": row.action,
        "qty": row.qty,
        "price": row.price,
        "cost_breakdown": row.cost_breakdown,
        "net_cash_flow": row.net_cash_flow,
        "decision_id": row.decision_id,
    }


def _snapshot_to_dict(row) -> dict:
    return {
        "id": row.id,
        "ts": row.ts,
        "cash": row.cash,
        "positions": row.positions,
        "portfolio_value": row.portfolio_value,
        "net_pnl": row.net_pnl,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/cycle/{symbol}")
def trigger_cycle(symbol: str, request: Request) -> dict:
    session = request.app.state.session_factory()
    try:
        log, price = run_cycle(session, request.app.state.portfolio, symbol.upper())
        return {"decision": log.model_dump(mode="json"), "price": price}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@app.post("/watchlist/run")
def trigger_watchlist(request: Request, execution_mode: str = "autonomous") -> list[dict]:
    """`execution_mode="manual"` defers actionable (BUY/SELL/SWITCH)
    decisions to /suggestions instead of auto-executing them -- see
    schemas.Suggestion and loop.run_watchlist_once."""
    if execution_mode not in EXECUTION_MODES:
        raise HTTPException(status_code=400, detail=f"execution_mode must be one of {sorted(EXECUTION_MODES)}.")
    if request.app.state.busy:
        raise HTTPException(status_code=409, detail="A session is already running.")
    request.app.state.busy = True
    request.app.state.progress.clear()
    request.app.state.progress.update({"phase": "starting", "mode": "watchlist", "detail": "Starting..."})
    session = request.app.state.session_factory()
    try:
        logs = run_watchlist_once(
            session, request.app.state.portfolio, progress=request.app.state.progress,
            execution_mode=execution_mode, suggestions=request.app.state.suggestions,
        )
        return [log.model_dump(mode="json") for log in logs]
    finally:
        session.close()
        request.app.state.busy = False
        request.app.state.progress["phase"] = "idle"


@app.post("/session/square-off")
def trigger_square_off(request: Request) -> list[dict]:
    """Manually forces every open position flat right now -- the same
    action that fires automatically when the session crosses market close.
    Exists so this control is demoable without waiting for the actual
    15:15 IST boundary."""
    session = request.app.state.session_factory()
    try:
        logs = square_off_all_positions(session, request.app.state.portfolio)
        return [log.model_dump(mode="json") for log in logs]
    finally:
        session.close()


@app.post("/replay/run")
async def trigger_replay(
    request: Request, max_bars: int = 20, seconds_per_tick: float = 0.0, execution_mode: str = "autonomous"
) -> dict:
    """Demo mode for outside market hours: plays cached historical bars for
    the whole watchlist in lockstep through run_watchlist_once -- the exact
    same allocator/stop-loss/cross-symbol-comparison path live trading uses,
    not a parallel implementation (an earlier version of this endpoint
    called the single-symbol replay path per symbol in a loop, bypassing
    the cross-symbol allocator and driving the book to a simulated -204%;
    see replay/player.py's module docstring).

    `execution_mode="manual"` defers actionable decisions to /suggestions
    instead of auto-executing them -- pair with a nonzero `seconds_per_tick`
    so there's actually time to click Execute before the next tick
    supersedes a symbol's suggestion (see schemas.Suggestion)."""
    if execution_mode not in EXECUTION_MODES:
        raise HTTPException(status_code=400, detail=f"execution_mode must be one of {sorted(EXECUTION_MODES)}.")
    if request.app.state.busy:
        raise HTTPException(status_code=409, detail="A session is already running.")
    request.app.state.busy = True
    request.app.state.progress.clear()
    request.app.state.progress.update({"phase": "starting", "mode": "replay", "detail": "Starting replay..."})
    try:
        await run_replay_session(
            request.app.state.session_factory,
            request.app.state.portfolio,
            max_bars=max_bars,
            seconds_per_tick=seconds_per_tick,
            progress=request.app.state.progress,
            execution_mode=execution_mode,
            suggestions=request.app.state.suggestions,
        )
    finally:
        request.app.state.busy = False
        request.app.state.progress["phase"] = "idle"
    return {"status": "complete", "max_bars": max_bars}


@app.get("/session/progress")
def session_progress(request: Request) -> dict:
    """Poll target for a running /watchlist/run or /replay/run pass. Shape
    depends on `phase`:
    - "idle" | "starting" | "error": just `phase`, `mode`, `detail`.
    - "discovering": + `universe_size`/`scanned`/`survived_scan`/
      `selected_count`/`watchlist` once Discovery finishes (see
      orchestration/watchlist.py).
    - "evaluating" | "executing": + `current_symbol`, `symbols_completed`,
      `symbols_total`.
    - replay mode additionally carries `bars_played`/`max_bars` once ticks
      start (see replay/player.py).
    All keys are best-effort -- a caller should treat any of them as
    possibly absent depending on how far the current pass has gotten."""
    return dict(request.app.state.progress)


@app.get("/suggestions")
def list_suggestions(request: Request) -> list[dict]:
    """Currently pending manual-mode decisions awaiting an execute click
    (see schemas.Suggestion) -- empty whenever no manual-mode session has
    run, or every pending symbol has since been superseded or executed."""
    return [s.model_dump(mode="json") for s in request.app.state.suggestions.values()]


@app.post("/suggestions/{symbol}/execute")
def execute_suggestion(symbol: str, request: Request) -> dict:
    """Executes a pending manual-mode suggestion -- at a price re-fetched
    right now, not the price it was suggested at, since intraday prices
    move in the time a human takes to decide (see schemas.Suggestion's
    docstring). 404s if the suggestion was already executed or has since
    been superseded by that symbol's next cycle."""
    symbol = symbol.upper()
    suggestion = request.app.state.suggestions.get(symbol)
    if suggestion is None:
        raise HTTPException(status_code=404, detail=f"No pending suggestion for {symbol}.")

    session = request.app.state.session_factory()
    try:
        fresh_context = build_context(symbol)
        executing_at = datetime.now(timezone.utc)
        log = finalize_cycle(
            session, request.app.state.portfolio, fresh_context,
            suggestion.consensus, suggestion.risk_verdict, suggestion.revised_recommendations, executing_at,
        )
        snapshot = request.app.state.portfolio.mark_to_market({symbol: fresh_context.latest_price})
        repository.insert_portfolio_snapshot(session, snapshot)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()

    # Removes whatever is there now, not necessarily `suggestion` itself --
    # if a background cycle superseded it in the narrow window above, that
    # newer entry is stale too (this symbol was just executed against).
    request.app.state.suggestions.pop(symbol, None)

    return {
        "decision": log.model_dump(mode="json"),
        "suggested_price": suggestion.suggested_price,
        "suggested_at": suggestion.suggested_at.isoformat(),
        "executing_price": fresh_context.latest_price,
        "executing_at": executing_at.isoformat(),
    }


@app.post("/discovery/run")
def run_discovery(request: Request, limit: int | None = None) -> dict:
    """Run one Opportunity Discovery cycle over the NSE universe and return the
    ~50-60 selected candidates with full factor/explainability breakdown.
    `limit` optionally caps the universe (handy for quick demos)."""
    from backend.committee.discovery.universe import load_universe

    agent = _get_discovery_agent(request.app)
    universe = load_universe(fetchable_only=agent._config.data.fetchable_only)
    if limit is not None:
        universe = universe[: max(1, limit)]
    try:
        result = agent.discover(universe)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    request.app.state.last_discovery = result
    return result.model_dump(mode="json")


@app.get("/discovery/latest")
def latest_discovery(request: Request) -> dict:
    """Most recent discovery result (404 until one has run)."""
    result = request.app.state.last_discovery
    if result is None:
        raise HTTPException(status_code=404, detail="No discovery run yet — POST /discovery/run first.")
    return result.model_dump(mode="json")


@app.get("/decisions")
def decisions(request: Request, stock: str | None = None) -> list[dict]:
    session = request.app.state.session_factory()
    try:
        return [_decision_to_dict(row) for row in repository.get_decision_log(session, stock)]
    finally:
        session.close()


@app.get("/trades")
def trades(request: Request, stock: str | None = None) -> list[dict]:
    session = request.app.state.session_factory()
    try:
        return [_trade_to_dict(row) for row in repository.get_trade_history(session, stock)]
    finally:
        session.close()


@app.get("/portfolio")
def portfolio_state(request: Request) -> dict:
    portfolio = request.app.state.portfolio
    return {"cash": portfolio.cash, "positions": portfolio.positions}


@app.get("/portfolio/curve")
def portfolio_curve(request: Request) -> list[dict]:
    session = request.app.state.session_factory()
    try:
        return [_snapshot_to_dict(row) for row in repository.get_portfolio_curve(session)]
    finally:
        session.close()


@app.get("/report")
def report(request: Request) -> dict:
    """Gross/costs/net P&L summary (Audit Layer) — the PS requires reporting
    net profit after all trading costs, not gross."""
    session = request.app.state.session_factory()
    try:
        curve = repository.get_portfolio_curve(session)
        portfolio_value = curve[-1].portfolio_value if curve else CAPITAL
        summary = summarize_pnl(session, portfolio_value)
        # current_capital is mark-to-market equity (cash + position value), not raw
        # cash -- shorting a stock inflates cash while the position carries an
        # offsetting negative value, so cash alone drifts away from real capital.
        # current_buying_power is derived from current_capital so it is always
        # exactly LEVERAGE times capital, never independently out of sync.
        current_capital = portfolio_value
        return {
            "base_capital": CAPITAL,
            "base_buying_power": BUYING_POWER,
            "current_capital": current_capital,
            "current_buying_power": current_capital * LEVERAGE,
            "portfolio_value": portfolio_value,
            "current_cash": request.app.state.portfolio.cash,
            "trade_count": summary.trade_count,
            "gross_pnl": summary.gross_pnl,
            "total_costs": summary.total_costs,
            "net_pnl": summary.net_pnl,
            "growth_pct": summary.growth_pct,
            "cost_breakdown_by_symbol": cost_breakdown_by_symbol(session),
        }
    finally:
        session.close()
