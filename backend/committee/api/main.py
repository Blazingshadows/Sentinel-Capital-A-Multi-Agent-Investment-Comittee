"""FastAPI surface — README's API/dashboard layer. Exposes the ability to
trigger committee cycles and read back the audit trail (decisions, trades,
portfolio curve) that every other layer already writes to SQLite. Building
the dashboard UI itself is out of scope for this pass; this is what it would
consume.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.committee.audit.report import cost_breakdown_by_symbol, summarize_pnl
from backend.committee.config import BUYING_POWER, CAPITAL, LEVERAGE
from backend.committee.execution.portfolio import Portfolio
from backend.committee.orchestration.cycle import run_cycle
from backend.committee.orchestration.loop import run_watchlist_once
from backend.committee.persistence import repository
from backend.committee.persistence.db import init_db, make_engine, make_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = make_engine()
    init_db(engine)
    app.state.session_factory = make_session_factory(engine)
    app.state.portfolio = Portfolio()
    app.state.discovery_agent = None  # built lazily on first /discovery call
    app.state.last_discovery = None
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
def trigger_watchlist(request: Request) -> list[dict]:
    session = request.app.state.session_factory()
    try:
        logs = run_watchlist_once(session, request.app.state.portfolio)
        return [log.model_dump(mode="json") for log in logs]
    finally:
        session.close()


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
