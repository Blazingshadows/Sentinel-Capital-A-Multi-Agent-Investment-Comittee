"""FastAPI surface — README's API/dashboard layer. Exposes the ability to
trigger committee cycles and read back the audit trail (decisions, trades,
portfolio curve) that every other layer already writes to SQLite. Building
the dashboard UI itself is out of scope for this pass; this is what it would
consume.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

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
    yield


app = FastAPI(title="Autonomous Multi-Agent Investment Committee", lifespan=lifespan)


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
