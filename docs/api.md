# API Reference

FastAPI app: `backend/committee/api/main.py`. Runs on `http://127.0.0.1:8000`
by default (`uvicorn backend.committee.api.main:app`). CORS is scoped to the
Vite dev server (`http://localhost:5173`, `http://127.0.0.1:5173`) — the
dashboard's own origin during development.

All response bodies are JSON. Pydantic models are serialized with
`.model_dump(mode="json")`, so enums come through as their string values
(`"BUY"`/`"SELL"`/`"WAIT"`, `"APPROVE"`/`"REDUCE"`/`"REJECT"`).

## Health

### `GET /health`

Liveness check.

```json
{"status": "ok"}
```

## Committee cycles

### `POST /cycle/{symbol}`

Runs one full committee cycle (agents → debate → consensus → risk →
execution → audit) for a single symbol, against live market data. Symbol is
upper-cased server-side. Returns `500` if any layer raises.

```json
{
  "decision": { /* DecisionLog, see below */ },
  "price": 2891.4
}
```

### `POST /watchlist/run`

Runs one cycle across the whole configured watchlist (`config.WATCHLIST`),
evaluating every symbol before executing any of them so the cross-symbol
capital allocator can see the full cycle's demand (see
`docs/architecture.md`). A single symbol's failure is logged and skipped,
not fatal to the rest of the pass. Returns a list of `DecisionLog`, one per
symbol that completed successfully.

### `POST /session/start`

Starts a background asyncio task that calls the equivalent of
`/watchlist/run` on a fixed interval while NSE market hours are open, and
idle-polls (checking every 30s) outside market hours instead of burning LLM
calls re-evaluating a frozen last bar. `409` if a session is already
running.

```json
{"running": true, "started_at": "2026-07-09T09:15:03.512Z"}
```

### `POST /session/stop`

Cancels the running session task, if any. Idempotent.

```json
{"running": false}
```

### `GET /session/status`

```json
{
  "running": true,
  "started_at": "2026-07-09T09:15:03.512Z",
  "market_hours": true,
  "interval_seconds": 300
}
```

## Opportunity Discovery

### `POST /discovery/run?limit={n}`

Runs one Opportunity Discovery cycle over the NSE universe
(`discovery/universe/nse_universe.json`, restricted to symbols with a
verified Breeze `stock_code`) and returns the ~50-60 selected candidates
with full factor/explainability breakdown. `limit` optionally caps the
universe size before scanning — useful for a fast demo run. The discovery
agent is built lazily on first call and cached on `app.state`. `500` if the
run raises.

```json
{
  "cycle_ts": "2026-07-09T09:15:00Z",
  "regime": "RISK_ON",
  "universe_size": 287,
  "scanned": 287,
  "survived_scan": 194,
  "selected_count": 58,
  "runtime_ms": 4213.7,
  "config_fingerprint": "a1b2c3d4e5f6",
  "scan_report": { "...": "ScanReport" },
  "candidates": [ { "...": "OpportunityCandidate, rank-ordered" } ],
  "dropped_sample": ["SYMBOL1", "SYMBOL2"],
  "diagnostics": { "score_dispersion": 12.4, "mean_confidence": 0.71, "...": "..." }
}
```

### `GET /discovery/latest`

Most recent discovery result from this process's memory. `404` until
`/discovery/run` has been called at least once since the process started.

## Audit trail

### `GET /decisions?stock={symbol}`

Full decision log — one row per cycle per stock ever evaluated, including
WAITs. Optional `stock` query param filters to one symbol. Each row:

```json
{
  "id": 1,
  "cycle_ts": "2026-07-09T09:15:00Z",
  "stock": "INFY",
  "agent_recommendations": [ { "agent": "Technical", "decision": "BUY", "confidence": 0.62, "reasoning": "...", "evidence": ["..."], "signed_vote": 0.62 } ],
  "debate": { "original_recommendations": [ "..." ], "contrarian_challenge": "...", "contrarian_risk_observations": ["..."], "revised_recommendations": [ "..." ] },
  "influence_breakdown": [ { "agent": "Technical", "confidence": 0.62, "trust_score": 0.55, "context_relevance": 1.2, "influence_raw": 0.41, "influence_normalized": 0.28, "signed_vote": 0.62 } ],
  "consensus_decision": "BUY",
  "consensus_confidence": 0.74,
  "consensus_allocation": 1.48,
  "consensus_reasoning": "Directional Confidence Score=+0.74 -> BUY. ...",
  "risk_action": "REDUCE",
  "risk_approved_allocation": 0.74,
  "risk_volatility_estimate": 0.52,
  "risk_reason": "Allocation trimmed from 1.48 to 0.74: ...",
  "action_taken": "BUY",
  "qty": 25.0,
  "price": 2891.4,
  "cost_breakdown": { "brokerage": 20.0, "stt": 0.0, "exchange_txn_charges": 2.15, "sebi_charges": 0.07, "stamp_duty": 2.17, "gst": 3.99, "slippage": 25.2, "total_cost": 53.58 },
  "net_cash_flow": -72338.58
}
```

### `GET /trades?stock={symbol}`

Executed orders only (a subset of `/decisions` — rows where `qty > 0`),
each FK'd back to the decision that triggered it via `decision_id`.

### `GET /portfolio`

Current in-memory portfolio state (cash + open positions), reconstructed on
process startup from the latest `portfolio_snapshots` row so a restart
doesn't lose track of what's actually been traded.

```json
{"cash": 8412.30, "positions": {"INFY": 25.0, "TCS": -10.0}}
```

### `GET /portfolio/curve`

Every mark-to-market snapshot ever recorded, in chronological order —
what the dashboard's portfolio value chart plots.

```json
[{"id": 1, "ts": "2026-07-09T09:15:05Z", "cash": 8412.30, "positions": {"INFY": 25.0}, "portfolio_value": 10087.55, "net_pnl": 87.55}]
```

### `GET /report`

Session-level P&L summary (Audit Layer) — the PS requires reporting *net*
profit after all trading costs, not gross.

```json
{
  "starting_value": 10000.0,
  "starting_cash": 20000.0,
  "portfolio_value": 10087.55,
  "current_cash": 8412.30,
  "trade_count": 4,
  "gross_pnl": 301.85,
  "total_costs": 214.30,
  "net_pnl": 87.55,
  "growth_pct": 0.88,
  "cost_breakdown_by_symbol": {
    "INFY": {"trade_count": 3, "total_costs": 160.10},
    "TCS": {"trade_count": 1, "total_costs": 54.20}
  }
}
```

`starting_value`/`starting_cash` are `config.CAPITAL` (₹10,000) and
`config.BUYING_POWER` (₹20,000 = capital × 1:2 leverage) — fixed constants,
not derived from trade history.
