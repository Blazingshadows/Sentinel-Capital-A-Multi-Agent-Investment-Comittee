# Architecture

This is the design doc for how the Autonomous Multi-Agent Investment
Committee is actually built, as opposed to `README.md`'s problem-statement
framing of what it's supposed to do. Read `README.md` first for the mission
and rules; this document is the implementation.

## Pipeline overview

Every watchlist symbol goes through the same pipeline once per cycle:

```
Market Data Layer
      |
      v
Specialist Agents (Technical, News & Sentiment, Macro, Forecasting)  -- independent, parallelizable
      |
      v
Debate Layer (Contrarian challenge + confidence revision)
      |
      v
Consensus Orchestrator (Dynamic Trust Framework -> BUY/SELL/WAIT + allocation)
      |
      v
Risk Management Layer (GARCH volatility check, position caps)
      |
      v
Cross-Symbol Capital Allocator (only in the watchlist loop, not single-symbol cycles)
      |
      v
Execution Layer (delta-sized order, NSE cost model, portfolio update)
      |
      v
Audit Layer (SQLite: decisions, trades, portfolio snapshots, trust scores)
```

The code mirrors this exactly: `backend/committee/orchestration/cycle.py`
(`evaluate_context` then `finalize_cycle`) is the one-symbol version of this
pipeline; `backend/committee/orchestration/loop.py`
(`run_watchlist_once`/`run_session`) runs it across the whole watchlist,
evaluating every symbol before executing any of them so the capital
allocator can see all of that cycle's demand at once.

Upstream of all of this sits a separate, optional stage:

```
Opportunity Discovery (NSE universe -> ~50-60 high-opportunity candidates)
      |
      v
   (candidates become the watchlist fed into the pipeline above)
```

Discovery never emits a directional call — it only narrows the search
space. See [Opportunity Discovery](#opportunity-discovery-subsystem) below
and `docs/agents.md` for the per-stage detail.

## Module map

| Layer (README) | Package | Key files |
|---|---|---|
| Market Data | `backend/committee/market_data/` | `breeze_client.py`, `prices.py`, `news.py`, `context.py` |
| Specialist Agents | `backend/committee/agents/` | `technical.py`, `news_sentiment.py`, `macro.py`, `forecasting.py` |
| Debate | `backend/committee/debate/` | `engine.py`, `contrarian.py` |
| Consensus Orchestrator | `backend/committee/consensus/`, `backend/committee/trust/` | `orchestrator.py`, `scoring.py` |
| Risk Management | `backend/committee/risk/` | `manager.py`, `volatility.py` |
| Execution | `backend/committee/execution/` | `portfolio.py`, `cost_model.py` |
| Audit | `backend/committee/audit/`, `backend/committee/persistence/` | `report.py`, `models.py`, `repository.py`, `db.py` |
| Orchestration (glue) | `backend/committee/orchestration/` | `cycle.py`, `loop.py`, `allocator.py` |
| Opportunity Discovery | `backend/committee/discovery/` | `agent.py`, `scanner.py`, `scoring.py`, `diversity.py` |
| Replay Mode | `backend/committee/replay/` | `player.py` |
| LLM routing | `backend/committee/llm/` | `router.py`, `gemini_client.py`, `openai_client.py`, `anthropic_client.py` |
| API | `backend/committee/api/` | `main.py` (FastAPI) |
| Dashboard | `frontend/` | Vite + TypeScript, no framework |
| Shared contracts | `backend/committee/schemas.py` | every pydantic model every layer speaks |
| Config | `backend/committee/config.py` | every tunable constant, in one place |

## Shared data contracts (`schemas.py`)

Nothing downstream needs to know how an upstream layer computed its output —
only its shape:

```
AgentOutput          -- one specialist's decision/confidence/reasoning/evidence
DebateResult         -- original + revised recommendations, contrarian challenge
AgentInfluence        -- one agent's confidence x trust x context_relevance breakdown
ConsensusDecision     -- symbol, decision, confidence, allocation, influence_breakdown, debate
RiskVerdict           -- action (APPROVE/REDUCE/REJECT), approved_allocation, volatility_estimate
CostBreakdown          -- brokerage/STT/exchange/SEBI/stamp-duty/GST/slippage -> total_cost
TradeRecord            -- executed (or skipped) order
PortfolioSnapshot       -- mark-to-market cash/positions/value/pnl
DecisionLog            -- one full audit row: consensus + risk_verdict + trade
```

`AgentOutput.signed_vote` is a computed field: `+confidence` for BUY,
`-confidence` for SELL, `0` for WAIT. This is what the Consensus Orchestrator
actually sums.

## Dynamic Trust Framework (Consensus Orchestrator)

The implemented formula (`backend/committee/trust/scoring.py`,
`backend/committee/consensus/orchestrator.py`) is a 3-factor version of
README's 6-factor formula — confidence, trust, and context relevance are
each modeled explicitly; expertise is folded into context relevance
(`config.BASE_EXPERTISE x CONTEXT_RELEVANCE_BOOST`), and inter-agent
agreement is handled upstream by the Debate Layer's confidence-revision pass
rather than as a fourth multiplicative term:

```
Agent Influence(raw)  = confidence x trust_score x context_relevance
influence_normalized  = influence_raw / sum(influence_raw across the committee this cycle)

Directional Confidence Score (DCS) = sum(influence_normalized x signed_vote)   # in [-1, 1]

if |DCS| < DECISION_THRESHOLD_WAIT (0.15):
    decision = WAIT, allocation = 0
else:
    decision = BUY if DCS > 0 else SELL
    allocation = min(|DCS| x LEVERAGE, LEVERAGE)   # Risk layer caps/trims this further
```

- **`trust_score`** — Laplace-smoothed hit rate over every *resolved*
  prediction the agent has made (`persistence/repository.update_trust_score`):
  `(correct + TRUST_PRIOR*2) / (total + 2)`. A cold-start agent starts at
  `TRUST_PRIOR = 0.5`, not 0 or 1 off one lucky call.
- **`context_relevance`** — `BASE_EXPERTISE[agent] x` the product of any
  matching context-flag boosts (`earnings_day`, `rbi_policy_day`, ...). This
  is README's "expertise x context relevance" folded into one factor.
- **Resolving predictions** — at the *start* of the next cycle for a stock,
  `backfill_prediction_outcomes` compares every open prediction against
  whether the latest two bars closed up/down/flat, and marks it
  correct/incorrect. This is why trust scores lag by exactly one cycle.

## Debate Layer

`backend/committee/debate/engine.py` implements README's 4-step flow as one
deterministic pass, not N further LLM calls:

1. The 4 specialist agents already produced independent recommendations.
2. The Contrarian (`contrarian.py`, its own LLM call) reviews all of them and
   casts its own vote plus a `challenge` and `risk_observations`.
3. Any agent whose call the Contrarian's vote *disagrees with* (both
   non-WAIT, opposite direction) gets its confidence damped:
   `revised = confidence x (1 - contrarian_confidence x REVISION_DAMPING_FACTOR)`
   (`REVISION_DAMPING_FACTOR = 0.5`, so a maximally-confident contrarian
   objection roughly halves the target's confidence; a low-confidence one
   barely moves it).
4. Agents the Contrarian agrees with (or has no opinion on) are left
   untouched — corroboration isn't grounds to revise.

The Contrarian's own (possibly revised-away) vote is *also* folded into the
consensus as a 5th input, weighted the same as everyone else via its own
trust/context_relevance.

## Risk Management Layer

`backend/committee/risk/manager.py`, pure Python over a GARCH(1,1) volatility
estimate (`risk/volatility.py`, via `arch`), annualized against
`INTRADAY_BARS_PER_DAY x TRADING_DAYS_PER_YEAR`. Falls back to plain
historical std when there's too little history for GARCH to converge.

```
WAIT consensus        -> APPROVE, allocation 0 (nothing to risk-check)
vol > EXTREME (100%)  -> REJECT outright
allocation capped at MAX_POSITION_ALLOCATION (1.0x buying power)
vol > HIGH (45%)      -> allocation *= VOLATILITY_TRIM_FACTOR (0.5)
otherwise             -> APPROVE as proposed (post-cap)
```

## Cross-symbol capital allocator

A single symbol's risk verdict has no visibility into what capital *other*
watchlist symbols want the same cycle — naively executing every approved
verdict against the full `BUYING_POWER` lets simultaneously-strong signals
jointly request far more capital than the portfolio actually has (the
allocator's docstring records a verified case: three simultaneous BUY
signals requested 291% of buying power and drove cash to -Rs 38,000).

`backend/committee/orchestration/allocator.py` fixes this: `loop.py`
evaluates every watchlist symbol first (agents through Risk, no capital
committed), then `allocate_capital` computes each symbol's *incremental*
capital need (target exposure minus what's already held), and if the sum
exceeds remaining headroom (`BUYING_POWER - current_gross_exposure`), scales
each symbol's incremental grant proportionally to its consensus confidence.
Trades that *reduce* exposure are never throttled — they free capital rather
than consume it. Only after this does `loop.py` call `finalize_cycle` (which
actually executes) for each symbol.

## Execution Layer

`backend/committee/execution/portfolio.py`. `risk_verdict.approved_allocation`
is a **target position size**, not an amount to add — the code computes
`target_qty` from the approved allocation and only trades the delta against
`portfolio.positions[symbol]`. This matters: without it, a signal that
persists for several cycles would keep buying more each cycle even though
each individual cycle respected its cap, letting exposure snowball past the
position limit over time. A signal already fully expressed in the current
position results in zero trade.

Every fill runs through `execution/cost_model.py` — a deterministic NSE
intraday retail cost model (brokerage capped at Rs 20 or 0.03%, STT on
sell-side only, exchange transaction charges, SEBI charges per crore, stamp
duty on buy-side only, 18% GST on brokerage+exchange charges, and a fixed
slippage assumption) — so "net profit after all trading costs" is a real,
itemized number, not an approximation.

## Persistence & Audit Layer

SQLite via SQLAlchemy (`backend/committee/persistence/`). Four tables:

- **`agent_predictions`** — one row per agent per cycle per stock;
  `outcome_direction`/`correct` filled in retroactively. Source of trust
  scores.
- **`decisions`** — one row per cycle per stock evaluated (whether or not a
  trade happened): full agent recommendations, debate, influence breakdown,
  consensus, risk verdict, and trade outcome as JSON columns. This is the
  end-to-end explainability record README requires for every trade *and*
  every no-trade.
- **`trades`** — one row per executed order, FK'd back to the `decisions`
  row that triggered it.
- **`portfolio_snapshots`** — periodic marks (cash, positions, portfolio
  value, net P&L) — the dashboard's portfolio curve and P&L report are
  computed from this table.
- **`trust_scores`** — one row per agent, the Dynamic Trust Framework's
  persisted state (`total_predictions`, `correct_predictions`, smoothed
  `trust_score`).

`backend/committee/audit/report.py` computes `PnLSummary`:
`gross_pnl = net_pnl + total_costs`, where `net_pnl` comes from
mark-to-market portfolio value (so it correctly includes unrealized P&L on
open positions, not just realized cash flow).

## Opportunity Discovery subsystem

`backend/committee/discovery/` is a separate, upstream, non-forecasting
stage (its own package, own config, own tests) that reduces the ~300-symbol
NSE universe down to the ~50-60 highest-opportunity names for the committee
to actually reason over. It never emits BUY/SELL and never forecasts a
price — it only selects the search space. Three internal stages, wired by
`registry.build_default_discovery_agent`:

```
MarketScannerAgent      -- high-recall pre-screen: liquidity/tradability/regime, one metric bundle per symbol
      |
OpportunityScoringAgent -- decorrelated, risk-adjusted, cross-sectional multi-factor score (0-100 percentile)
      |
DiversityOptimizerAgent -- sector cap + shrunk-correlation clustering + capacity tilt -> target 50-60 names
```

Every stage depends only on the abstract ports in `discovery/interfaces.py`
(`AbstractMarketScanner`, `AbstractOpportunityScorer`,
`AbstractDiversityOptimizer`, `MarketDataPort`) — dependency inversion so
tests inject an `InMemoryDataProvider` and exercise the full pipeline with
no network or Breeze mapping required. See `docs/agents.md` for the factor
list and scoring math, and `backend/committee/discovery/config.py` /
`discovery/config/default_config.json` for every tunable (there are no
magic numbers in the algorithm modules — everything lives in
`DiscoveryConfig`).

The universe itself (`discovery/universe/nse_universe.json`) is a data
asset: `{symbol, sector, stock_code}` triples. Only symbols with a verified
Breeze `stock_code` are live-fetchable (`load_universe(fetchable_only=True)`,
the API default); `register_breeze_codes()` merges verified codes into
`config.BREEZE_STOCK_CODE_MAP` so `prices.fetch_ohlcv` can resolve them.

Discovery output doesn't yet feed the watchlist automatically — today it's
its own read/trigger pair on the API (`POST /discovery/run`,
`GET /discovery/latest`, see `docs/api.md`) that a caller (or a future
scheduler) can use to refresh which symbols the committee should watch.

## Replay Mode

`backend/committee/replay/player.py`. Built as just an alternate
`MarketContext` source behind `orchestration.cycle.process_context` — not a
separate pipeline. `ReplayFeed` walks a cached OHLCV file bar-by-bar
(starting at index 50, since the Technical agent needs EMA50 history before
its first read) and calls `process_context` once per bar at
`seconds_per_bar` pacing. Useful when a demo/judging slot falls outside NSE
market hours: replay a cached day's bars at accelerated speed through the
exact same pipeline live trading uses.

## LLM routing & provider diversity

`backend/committee/llm/router.py` dispatches each LLM-backed agent
(News & Sentiment, Macro, Contrarian) to its own provider per
`config.AGENT_PROVIDER_MAP` — Gemini, OpenAI, and Anthropic respectively.
This is deliberate: an LLM agent's reasoning is shaped by its training, not
just its prompt, so routing different specialists through different labs'
models gives the Debate Layer genuinely independent points of view instead
of one model role-playing three personas. The Contrarian (devil's-advocate
role) is routed to the provider judged most likely to actually disagree.

Every provider client enforces structured JSON output validated against a
pydantic schema (`LLMAgentVerdict` or `ContrarianVerdict`), retries once on a
malformed response, and raises a single unified `LLMUnavailableError` on
failure. Every LLM-backed agent catches that error and degrades to a
neutral `WAIT` (confidence 0) with an explanatory `reasoning` string instead
of crashing the cycle — a missing API key or a rate limit never takes down
the whole committee, only that one agent's vote for that one cycle.

## Forecasting Agent

The one non-LLM specialist beyond Technical: a LightGBM classifier
(`backend/committee/agents/forecasting.py`), trained offline by
`scripts/train_forecasting_model.py`. Deliberately a gradient-boosted tree
rather than an LSTM/deep model — trains in seconds on modest intraday
history, resists overfitting a short window, and gives feature importances
as a built-in explainability story instead of an opaque hidden state.
Labels are 3-class (bearish/neutral/bullish) over a
`FORECAST_LOOKAHEAD_BARS`-bar horizon, with a volatility-scaled deadzone
(not a fixed return threshold) so a calm stock's noise and a volatile
stock's real moves aren't mislabeled the same way when pooled for training.
See `docs/agents.md` for the full feature list.

## Market data source: ICICI Direct Breeze API

Migrated from yfinance (see git history: "Migrate market data source from
yfinance to ICICI Breeze API"). `backend/committee/market_data/breeze_client.py`
is the only module that knows Breeze's request/response shape; every caller
still sees the same `Open/High/Low/Close/Volume` DataFrame contract yfinance
used to provide. Reasons this module exists and what it works around:

- Breeze's `get_historical_data_v2` only supports 1s/1m/5m/30m/1d buckets —
  no native 15-minute bar, which is why the whole project (Forecasting
  labels, Technical indicators, Discovery scanning) standardized on 5-minute
  bars.
- Max 1000 candles per request; wide date ranges are chunked and stitched.
- The session token (`BREEZE_SESSION_TOKEN`) is a daily, manually-generated
  value — SEBI requires an actual browser login every trading day, no
  automated refresh exists. A stale/missing token surfaces as
  `BreezeAuthError` with a pointer to re-authenticate. See `docs/setup.md`
  for the daily login flow.
- Breeze has no fundamentals/sector data (it's a trading API, not a data
  vendor) — `config.WATCHLIST_FUNDAMENTALS` is a small static table that
  replaces yfinance's `.info` for the two fields the Macro agent reads
  (sector, market cap); the Discovery universe carries its own sector map in
  `nse_universe.json` for the same reason.
- `config.BREEZE_STOCK_CODE_MAP` translates each NSE tradingsymbol (e.g.
  `RELIANCE`) to Breeze's own `stock_code` (e.g. `RELIND`) — these are not
  the same string, and only symbols in this map are live-fetchable.

`market_data/prices.py` caches every fetch to `data/historical/*.csv`,
merging (not overwriting) on each call, and falls back to the last cached
pull if a live fetch fails — a network hiccup never turns into a silent
empty result mistaken for "no signal."

## Dashboard

`frontend/` — Vite + vanilla TypeScript (no framework), talking to the
FastAPI backend on `http://127.0.0.1:8000` (CORS-scoped to the Vite dev
server origin, `localhost:5173`). Renders portfolio stat tiles, a portfolio
value chart, the watchlist decisions table with full per-decision
drill-down (agent votes, debate, influence breakdown, risk verdict, trade),
and the trade log. See `docs/api.md` for the endpoints it consumes.
