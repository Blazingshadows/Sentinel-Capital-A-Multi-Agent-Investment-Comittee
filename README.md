# Autonomous Multi-Agent Investment Committee
### PS #10 — Directional Confidence-Aware Consensus for Intraday Paper Trading (NSE/BSE)

This document is the problem statement and design mission the system is
built against. For how it's actually implemented today — architecture,
agent specs, API reference, and how to run it — see:

- **[docs/architecture.md](docs/architecture.md)** — system design, data flow, module map
- **[docs/agents.md](docs/agents.md)** — per-agent specs (inputs, logic, outputs, failure behavior)
- **[docs/api.md](docs/api.md)** — REST API reference
- **[docs/setup.md](docs/setup.md)** — install, configure, run, train, test

See [Implementation Snapshot](#implementation-snapshot) below for how the
current codebase maps onto the requirements in this document.

## Problem Statement

Retail and institutional investors face an overwhelming amount of market information every day:

- Price movements
- Technical indicators
- News events
- Macroeconomic developments
- Risk factors

Traditional trading systems often rely on a single model or strategy, making decisions based on a limited perspective. Human investment committees solve this problem by bringing together specialists with different viewpoints who debate, challenge assumptions, and collectively arrive at a decision.

The challenge is to build an Autonomous Multi-Agent Investment Committee capable of:

- Analyzing market data
- Forming independent opinions
- Debating conflicting viewpoints
- Reaching a **Directional Confidence-Aware Consensus** (not majority vote, not confidence averaging)
- Managing risk before capital deployment
- Executing paper trades autonomously, intraday, on the Indian market

## Objective

Build an Autonomous Multi-Agent Investment Committee that performs **real-time intraday paper trading on the Indian stock market (NSE/BSE)**, starting with **₹10,000 virtual capital** and **1:2 leverage**. The system must autonomously decide to **BUY, SELL, HOLD, WAIT, or SWITCH** stocks to **maximize end-of-day net profit (after all trading costs)** through explainable multi-agent reasoning.

Explainability is a hard requirement, not a substitute for the profit objective: the committee is judged on realized, cost-adjusted returns, and every one of those decisions must be traceable to the reasoning that produced it.

### Mandatory: Directional Confidence-Aware Consensus

**Simple majority voting or confidence averaging is not allowed.**

The final decision must use a Directional Confidence-Aware Consensus, where each agent's influence dynamically depends on all of the following:

1. **Confidence** — the agent's own certainty in its call
2. **Expertise** — how qualified the agent is for the current situation (e.g. a Technical agent's expertise is discounted on an earnings-driven move)
3. **Historical reliability** — the agent's track record of being directionally correct
4. **Trust** — a slower-moving, calibration-adjusted score built from reliability over time
5. **Context relevance** — how applicable the agent's specialty is to the current market regime
6. **Agreement / disagreement with other agents** — whether the agent's call is corroborated or contradicted by the rest of the committee

Every trade must clearly explain **why** the consensus reached its decision, citing which agents drove it and why they were weighted as they were.

---

## Trading Rules

| Parameter | Value |
|---|---|
| Market | NSE/BSE (Intraday) |
| Virtual Capital | ₹10,000 |
| Leverage | 1:2 |
| Session Length | 4–6 hours (single trading day) |
| Position Closure | All positions must be closed before market close |
| Cost Accounting | Profit calculated after realistic trading costs (brokerage, taxes, charges) |

### Decision Space

Every cycle, the committee must output one of five actions per stock under consideration:

- **BUY** — open/increase a long position
- **SELL** — close/reduce a long position
- **HOLD** — maintain the current position, no change
- **WAIT** — take no position; insufficient conviction or unfavorable setup
- **SWITCH** — exit the current holding and rotate capital into a higher-conviction alternative

---

# Proposed Solution

We propose an autonomous committee of specialized AI investment analysts, each responsible for evaluating the market from a unique perspective, operating on a compressed intraday clock (4–6 hours, NSE/BSE).

Instead of relying on a single predictive model, the system creates a structured decision-making process:

1. Gather market information (NSE/BSE live/delayed feeds).
2. Generate independent recommendations from specialist agents, each backed by a custom-built AI/ML tool.
3. Conduct an argumentation and challenge phase.
4. Aggregate recommendations through a **Directional Confidence-Aware Consensus orchestrator** (never majority vote or plain averaging).
5. Validate decisions through a dedicated risk manager, respecting the ₹10,000 / 1:2 leverage constraints.
6. Execute intraday paper trades.
7. Track performance and continuously update trust, reliability, and calibration scores.
8. Close all open positions before market close and report final, cost-adjusted results.

The final output is not simply BUY/SELL/HOLD/WAIT/SWITCH, but a capital allocation recommendation with supporting evidence, agent-level attribution, and risk justification.

---

# Core Design Principles

## Independent Reasoning
Each agent must reason independently before seeing the opinions of other agents.

## Constructive Disagreement
Disagreement is encouraged rather than avoided. Agreement/disagreement between agents is itself a signal that feeds the consensus weighting.

## Dynamic, Multi-Factor Trust
Agent influence is never static and never a single number — it is the product of confidence, expertise, historical reliability, trust, context relevance, and inter-agent agreement.

## Explainability
Every recommendation, every HOLD/WAIT, and every no-trade decision must be traceable to supporting evidence.

## Risk First
No trade can be executed without risk review and approval against the ₹10,000 capital base and 1:2 leverage limit.

## Cost-Aware Profit Maximization
The committee is optimizing for end-of-day net profit after brokerage, taxes, and charges — not gross directional accuracy.

---

# System Architecture

## 1. Market Data Layer

Responsible for collecting and normalizing NSE/BSE data.

### Inputs
- Live / delayed NSE/BSE stock prices
- OHLCV data
- Market indices
- News headlines
- Sector information
- Corporate/policy/geopolitical events

### Output
Unified market context object.

---

## 2. Specialist Agent Layer

Each specialist agent is backed by a **custom-built** AI/ML tool (APIs may be used as inputs, but the analytical logic must be built by the team, not a thin wrapper over a third-party signal). Together, the agents must cover all eight mandatory tool categories from the problem statement.

| Agent | Mandatory Tool Category Covered | Focus | Output |
|---|---|---|---|
| Technical Analyst Agent | Technical Indicator Engine | RSI, MACD, moving averages, momentum | BUY/SELL/HOLD/WAIT/SWITCH, confidence, evidence |
| News & Sentiment Agent | News & Sentiment Analysis | Financial news, earnings, corporate announcements | BUY/SELL/HOLD/WAIT/SWITCH, confidence, evidence |
| Forecasting Agent | Time-Series / DL Forecasting | Short-horizon price/volatility forecasts (intraday) | Directional forecast, confidence, evidence |
| Fundamental Analyst Agent | Fundamental Analysis | Valuation, earnings quality, balance-sheet signals | BUY/SELL/HOLD/WAIT/SWITCH, confidence, evidence |
| Macro & Policy Agent | Policy & Geopolitical Impact | Rate decisions, government policy, geopolitical shocks | BUY/SELL/HOLD/WAIT/SWITCH, confidence, evidence |
| Sector Intelligence Agent | Sector Intelligence | Sector rotation, peer-relative strength | BUY/SELL/HOLD/WAIT/SWITCH, confidence, evidence |
| Opportunity Discovery Agent | Opportunity Discovery | Screens NSE/BSE universe for SWITCH candidates | Ranked alternative stock list, confidence |
| Risk Prediction Agent | Risk Prediction | Forward-looking volatility/drawdown/tail-risk estimate | Risk score, confidence, evidence |
| Contrarian Agent | — (cross-cutting) | Challenges consensus assumptions, surfaces blind spots | Counterarguments, risk observations, confidence adjustments |

All specialist agents (except the Contrarian) output a directional call from the full five-action space, a confidence score, and supporting evidence.

> **Implementation note:** the current codebase implements Technical, News & Sentiment, Macro, Forecasting, and Contrarian as the five agents driving each committee cycle, plus a separate Opportunity Discovery subsystem covering universe screening (see [Implementation Snapshot](#implementation-snapshot)). Fundamental Analysis, Sector Intelligence, and Risk Prediction are covered as factors/logic inside other layers rather than as standalone specialist agents today — see the snapshot for the detailed mapping.

---

## 3. Debate Layer

The debate layer enables structured interaction between agents.

### Flow

**Step 1** — Independent recommendations from all specialist agents.
**Step 2** — Agents review opposing opinions and note agreement/disagreement with each peer.
**Step 3** — Contrarian agent challenges assumptions, flags blind spots.
**Step 4** — Agents may revise confidence scores based on the challenge.

### Output
- Final committee recommendations (one of BUY/SELL/HOLD/WAIT/SWITCH)
- Updated confidence levels
- Per-pair agreement/disagreement matrix (feeds the consensus orchestrator)

---

## 4. Consensus Orchestrator — Directional Confidence-Aware Consensus

Responsible for synthesizing committee opinions using the mandatory multi-factor formula. **Never** a majority vote or plain confidence average.

### Inputs
- Agent recommendations (BUY/SELL/HOLD/WAIT/SWITCH)
- Confidence scores
- Expertise weighting for current context
- Historical reliability scores
- Trust scores
- Context relevance scores
- Agreement/disagreement matrix from the Debate Layer

### Agent Influence Formula

```
Agent Influence =
    Confidence
  × Expertise (context-weighted)
  × Historical Reliability
  × Trust Score
  × Context Relevance
  × Agreement Factor (peer corroboration / contradiction)
```

The consensus verdict is the confidence-weighted resolution of all agent influences into a single directional call, with a committee-level confidence score.

### Output — Per-Trade Report

Every BUY / SELL / HOLD / WAIT / SWITCH decision must report:

```json
{
  "symbol": "INFY",
  "decision": "BUY",
  "allocation": 0.25,
  "directional_confidence": 0.74,
  "agent_recommendations": [
    {"agent": "Technical", "call": "BUY", "confidence": 0.82},
    {"agent": "News", "call": "BUY", "confidence": 0.77},
    {"agent": "Macro & Policy", "call": "WAIT", "confidence": 0.65}
  ],
  "consensus_verdict": "BUY",
  "reasoning_and_evidence": "Momentum + earnings beat outweigh sector-level caution; contrarian flagged rally sustainability risk.",
  "alternative_stocks_considered": ["TCS", "WIPRO"],
  "critic_feedback": "Contrarian agent questioned sustainability of rally given sector weakness.",
  "expected_risk_return": {"expected_return": 0.03, "risk_score": 0.41}
}
```

---

## 5. Risk Management Layer

Final approval authority, enforcing the ₹10,000 capital base and 1:2 leverage limit.

### Responsibilities
- Position size control within leveraged capital
- Exposure limits
- Volatility checks (informed by the Risk Prediction Agent)
- Portfolio diversification
- Capital preservation
- Enforcing forced position closure before market close

### Actions
- Approve trade
- Reduce allocation
- Reject trade

---

## 6. Execution Layer

Responsible for:
- Intraday paper trade execution on NSE/BSE
- Portfolio updates
- Transaction logging
- Closing all open positions before market close
- Deducting brokerage, taxes, and charges from realized P&L

### Outputs
- Trade history
- Portfolio state
- Performance statistics

---

# Opportunity Discovery Agent

An **upstream, non-forecasting** stage (`backend/committee/discovery/`) that reduces the broad NSE universe (~230 sector-labelled names, extensible) to the ~50–60 highest-opportunity candidates the committee then reasons over. It **never predicts prices, never emits BUY/SELL, never forecasts returns** — it only shrinks the search space so the expensive committee spends its cycles on informative names.

### Pipeline

```
OpportunityDiscoveryAgent
    -> MarketScannerAgent       liquidity / tradability / ATR / ADX / vol / regime  (high recall)
    -> OpportunityScoringAgent  decorrelated, risk-adjusted multi-factor Opportunity Score
    -> DiversityOptimizerAgent  sector caps + shrunk-correlation clustering + capacity tilt
    -> ~50–60 ranked, fully-explained candidates
```

### Factor engineering (quant-grade)

Signals are aggregated from OHLCV into independent dimensions: **risk-adjusted, horizon-normalized momentum** (information-ratio, not raw returns), **relative strength** (idiosyncratic vs sector), **trend quality** (Kaufman efficiency ratio), **mean-reversion** (EMA-stretch in ATR units), **breakout** (range position), **volume expansion** (seasonality-robust relative volume), **volatility *expansion*** (short/long realized-vol ratio, not raw level), **liquidity**, a vol-scaled **event** surprise, and a **risk penalty**. Reuses the existing RSI/EMA/MACD primitives from `agents/technical.py`; only ATR/ADX/efficiency/vol-expansion/stretch are added.

### Scoring (the Opportunity Score)

Each factor is standardized **cross-sectionally** (robust median/MAD) with a **soft-winsor (tanh)** that preserves the ordering of the biggest movers instead of hard-clipping them (a false-negative guard). Factors are then **decorrelation-weighted** — down-weighted by their cross-sectional correlation each cycle — so the momentum family isn't counted four times (the promised orthogonalization, kept explainable via reported effective weights). The composite becomes a robust **percentile** Opportunity Score. Weights and every threshold are configuration (`discovery/config/default_config.json`); nothing is hard-coded.

### Confidence & explainability

Confidence is a weighted **geometric mean** of data completeness, cross-sectional significance, **signed** factor agreement (fixing a bias where magnitude factors always read as agreeing), and a **jackknife stability** term (does the name stay top-K under leave-one-factor-out?). Every candidate carries its factor scores, signed contributions and **%-of-score**, a dominant-**theme** tag, a confidence decomposition, reasoning, and a selection explanation — all machine-readable JSON.

### Diversification (large-AUM aware)

De-duplication uses a per-sector cap, correlation clustering on a **Ledoit-Wolf shrunk** covariance (a raw short-window correlation over many names is too unstable to trust), and a greedy submodular similarity penalty. Selection is **capacity-aware**: for a large book, opportunity value is edge × deployable size, so the marginal value is tilted toward high-turnover names. A recall top-up guarantees the list never falls below the minimum target.

### Integration & data source

Clean architecture with Dependency Injection: each stage depends only on the abstract ports in `discovery/interfaces.py`, wired at the composition root `discovery/registry.py::build_default_discovery_agent`. Market data flows through the existing **Breeze**-backed `market_data` layer behind a swappable `MarketDataPort`; sector labels and Breeze `stock_code`s live in the universe asset (`discovery/universe/nse_universe.json`) since Breeze has no fundamentals. Only symbols with a verified Breeze code are live-fetchable (`load_universe(fetchable_only=True)`); add codes to widen the live universe. It plugs into the committee by producing the `watchlist` argument `run_watchlist_once` already accepts — no existing agent, consensus, risk, or execution code is modified.

### Usage

```python
from backend.committee.discovery import build_default_discovery_agent
result = build_default_discovery_agent().discover()   # DiscoveryResult (machine-readable JSON)
symbols = result.selected_symbols                       # feed to the committee watchlist
```

API: `POST /discovery/run` (optional `?limit=N`) and `GET /discovery/latest`. Orchestration helper: `orchestration/discovery_cycle.py`.

---

# Dynamic Trust Framework

Each agent maintains independently tracked scores:

- **Historical reliability** — hit rate of directionally correct calls
- **Trust score** — slower-moving composite of reliability and calibration quality over time
- **Context relevance** — how applicable the agent's specialty is right now (e.g. News agent relevance spikes around earnings)
- **Expertise weighting** — situational competence for the current market regime
- **Agreement factor** — how corroborated or contradicted the agent's call is by the rest of the committee this cycle

This prevents static voting and enables adaptive, non-uniform committee behavior, in compliance with the "no majority vote / no confidence averaging" mandate.

---

# Evaluation Metrics

## Financial Metrics
- **Final Portfolio Value**
- **Net Profit** (after brokerage, taxes & charges)
- **Portfolio Growth** (% change from ₹10,000 base)
- **Sharpe Ratio**
- **Maximum Drawdown**
- **Win Rate**

## Agent Metrics
- **Agent Accuracy** — % of correct directional predictions
- **Confidence Calibration** — how well confidence aligns with outcomes
- **Trust Stability** — consistency of trust score updates
- **Debate Contribution** — impact of agent challenges on final decisions

## Consensus Metrics
- **Consensus Quality** — performance vs. individual agents
- **Decision Diversity** — measure of disagreement and viewpoint diversity
- **Allocation Efficiency** — capital deployed relative to confidence

## Risk Metrics
- **Risk Compliance** — % of trades approved under risk rules (₹10,000 / 1:2 leverage)
- **Exposure Control** — adherence to position limits
- **Portfolio Stability** — volatility of portfolio returns

---

# Success Criteria

## Minimum Viable Success
- All 8 mandatory AI/ML tool categories represented (custom-built, not solely API wrappers)
- Structured debate workflow
- Directional Confidence-Aware Consensus generation (no majority vote / averaging)
- Risk manager approval layer enforcing ₹10,000 capital and 1:2 leverage
- Intraday paper trading execution on NSE/BSE
- Explainable trade logs, including full per-trade report fields

## Good Success
- Full 6-factor dynamic trust/influence scoring
- Historical performance tracking
- Portfolio allocation recommendations across the 5-action decision space (incl. SWITCH)
- Interactive committee dashboard
- All positions verifiably closed before market close each session

## Excellent Success
- Adaptive trust updates
- Multi-stock portfolio management with live SWITCH decisions
- Historical replay evaluation
- Fully explainable committee reasoning for every trade **and** every no-trade (WAIT/HOLD)
- Real-time paper trading demonstration with complete decision log and cost-adjusted P&L

---

# Demo Scenario

## Input
Stock: INFY (NSE)

Market Data:
- Positive earnings
- Rising momentum
- Sector weakness
- Trading session: intraday, 4–6 hours, ₹10,000 virtual capital, 1:2 leverage

## Committee Opinions
- Technical Agent: BUY (0.82)
- News Agent: BUY (0.77)
- Fundamental Agent: BUY (0.70)
- Macro & Policy Agent: WAIT (0.65)
- Sector Intelligence Agent: WAIT (0.60)
- Risk Prediction Agent: Moderate volatility flagged
- Contrarian Agent: Questions sustainability of rally

## Consensus
Recommended Allocation: 25% of virtual capital
Directional Confidence: 74%
Decision: BUY

## Risk Review
Position approved. Allocation reduced to 20% due to volatility and leverage exposure limits.

## Execution
BUY INFY intraday → Portfolio updated → Position flagged for mandatory closure before market close → Decision, including agent-wise votes, critic feedback, and expected risk/return, stored in the audit log.

## End-of-Session Report
- Final Portfolio Value
- Net Profit (after brokerage, taxes & charges)
- Portfolio Growth %
- Trade History
- Explainable reasoning for every trade and every WAIT/HOLD decision
- Complete decision log

---

# Key Innovation

Most AI trading systems attempt to predict the market using a single model. Our system instead models the collaborative decision-making process of a real investment committee — where multiple specialist experts debate, challenge assumptions, build multi-factor trust over time, and allocate leveraged capital through a Directional Confidence-Aware Consensus that is explainable down to the individual agent vote — while operating under the real constraints of intraday NSE/BSE paper trading: fixed capital, leverage, a hard session clock, and realistic trading costs.

---

# Implementation Snapshot

What's actually built, as of the ICICI Breeze migration and the Opportunity
Discovery subsystem. Full detail lives in `docs/` (linked above); this is
the map from problem-statement language to real code.

## Requirement → implementation

| PS Requirement | Status | Where |
|---|---|---|
| Technical Indicator Engine | Implemented — RSI, MACD, EMA cross, momentum, pure pandas/numpy | `backend/committee/agents/technical.py` |
| News & Sentiment Analysis | Implemented — LLM-backed (Gemini), RSS-sourced headlines | `backend/committee/agents/news_sentiment.py`, `market_data/news.py` |
| Time-Series / DL Forecasting | Implemented — LightGBM classifier, offline-trained | `backend/committee/agents/forecasting.py`, `scripts/train_forecasting_model.py` |
| Policy & Geopolitical Impact | Implemented — LLM-backed (OpenAI) Macro agent | `backend/committee/agents/macro.py` |
| Contrarian / cross-cutting challenger | Implemented — LLM-backed (Anthropic), dual role in the Debate Layer | `backend/committee/debate/contrarian.py`, `debate/engine.py` |
| Opportunity Discovery | Implemented — scan → score → diversify over a 233-symbol NSE universe (229 live-fetchable via Breeze), wired into session watchlist selection at the start of every autonomous/replay run | `backend/committee/discovery/`, `orchestration/watchlist.py` (`docs/agents.md` §Opportunity Discovery) |
| Fundamental Analysis | Partial — static sector/market-cap table feeds the Macro agent's prompt; no dedicated agent (Breeze has no fundamentals endpoint) | `config.WATCHLIST_FUNDAMENTALS` |
| Sector Intelligence | Partial — sector-relative-strength is one of Discovery's 11 scoring factors; no dedicated live agent | `discovery/scoring.py` (`sector_strength` factor) |
| Risk Prediction | Implemented as the Risk Management Layer's own GARCH(1,1) volatility check, not a separate specialist vote | `backend/committee/risk/volatility.py`, `risk/manager.py` |
| Directional Confidence-Aware Consensus (no majority vote/averaging) | Implemented — `Confidence x Trust x Context Relevance`, normalized across the committee | `backend/committee/consensus/orchestrator.py`, `trust/scoring.py` |
| Debate Layer (independent → challenge → revise) | Implemented as one deterministic confidence-damping pass, not further LLM calls | `backend/committee/debate/engine.py` |
| Dynamic Trust Framework | Implemented — Laplace-smoothed historical reliability + context relevance; expertise folded into context relevance, agreement handled by the Debate Layer | `backend/committee/trust/scoring.py` |
| Risk Management (₹10,000 / 1:2 leverage) | Implemented — position cap, volatility trim/reject, cross-symbol capital allocator, plus a hard 3% stop-loss that force-closes a held position next cycle regardless of the committee's directional view | `backend/committee/risk/manager.py`, `orchestration/allocator.py`, `orchestration/loop.py::_apply_stop_loss`, `config.STOP_LOSS_PCT` |
| Execution + real NSE costs | Implemented — brokerage/STT/exchange/SEBI/stamp-duty/GST/slippage, delta-sized orders | `backend/committee/execution/` |
| Forced closure before market close | Implemented — the watchlist loop auto-flattens every open position the instant it crosses the `SESSION_SQUARE_OFF` (15:15 IST) boundary, plus an on-demand `POST /session/square-off` for demoing the control outside that window | `orchestration/loop.py::square_off_all_positions`, `orchestration/loop.py::run_forever` |
| Explainable per-trade audit log | Implemented — every cycle (trade or no-trade) persisted with full agent/debate/consensus/risk detail | `backend/committee/persistence/`, `audit/report.py` |
| Manual mode (human-in-the-loop execution) | Implemented — `execution_mode="manual"` defers BUY/SELL/SWITCH decisions to a suggestion queue instead of auto-executing; a human clicks Execute in the dashboard, which re-fetches the price fresh at click time rather than trading at the (possibly stale) suggested price | `api/main.py` (`/suggestions`, `/suggestions/{symbol}/execute`), `schemas.Suggestion`, `orchestration/loop.py::run_watchlist_once` |
| Interactive dashboard | Implemented — Vite + TypeScript, portfolio curve, decision drill-down, trade log, session run/stop control, autonomous/manual mode toggle with suggestion cards, and live progress polling (discovering/evaluating/executing/replay-tick phases) while a watchlist or replay pass is running | `frontend/` |
| Historical replay evaluation | Implemented — bar-by-bar replay through the exact same allocator/stop-loss/cross-symbol path live trading uses, not a parallel implementation | `backend/committee/replay/player.py` |
| Baseline comparison | Implemented — vectorbt SMA-crossover, matched cash/costs/methodology, parallelized one symbol per worker process | `backend/committee/baseline/`, `scripts/compare_baseline.py` |
| Performance (multi-symbol passes) | Implemented — per-symbol OHLCV fetch and agent evaluation within a watchlist pass are parallelized (`ThreadPoolExecutor`), not looped serially | `orchestration/loop.py` |

## Tech stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy + SQLite, pandas/numpy/scikit-learn, `arch` (GARCH), LightGBM, `breeze-connect`
- **LLMs:** Gemini, OpenAI, and Anthropic — one provider per LLM-backed agent, by design (see `docs/architecture.md` §LLM routing)
- **Market data:** ICICI Direct Breeze API (migrated from yfinance — SEBI requires a daily manual login; see `docs/setup.md`)
- **Frontend:** Vite + vanilla TypeScript, no framework
- **Testing:** pytest, an in-memory SQLite fixture, and a vectorbt-based baseline comparison

---

# Setup & Execution

This is a condensed, copy-pasteable version of the full walkthrough in
[docs/setup.md](docs/setup.md) — read that file for the "why" behind each
step (e.g. why Breeze needs a daily login, what each config knob does).

## 1. Prerequisites

- Python 3.11+
- Node.js 18+ (for the dashboard)
- An [ICICI Direct Breeze API](https://api.icicidirect.com/apiuser/home) app
  — required for live market data. Without it, `fetch_ohlcv` falls back to
  whatever's already cached in `data/historical/*.csv`, which is enough for
  Replay Mode and offline development but not for a live symbol that's
  never been fetched before.
- API keys for **Gemini**, **OpenAI**, and **Anthropic** — each LLM-backed
  agent (News & Sentiment, Macro, Contrarian) degrades to a neutral WAIT if
  its key is missing, so the committee still runs without all three, just
  with fewer live opinions.

## 2. Install dependencies

```bash
git clone <this-repo-url>
cd "Investment Committee"

# Backend (installs FastAPI, SQLAlchemy, pandas/numpy/scikit-learn, arch,
# breeze-connect, lightgbm, vectorbt, and the three LLM SDKs, plus
# pytest/pytest-asyncio via the [dev] extra)
pip install -e ".[dev]"

# Frontend
cd frontend
npm install
cd ..
```

## 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```
GEMINI_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
NEWSAPI_KEY=
DATABASE_URL=sqlite:///./data/committee.db

BREEZE_API_KEY=
BREEZE_API_SECRET=
BREEZE_SESSION_TOKEN=
```

`BREEZE_API_KEY` / `BREEZE_API_SECRET` are static — generate them once from
your app at https://api.icicidirect.com/apiuser/home ("View Apps").

`BREEZE_SESSION_TOKEN` is **not** static: SEBI requires a manual browser
login every trading day. Each morning before running the committee against
live data:

1. Log in at https://api.icicidirect.com/apiuser/home.
2. Copy the `api_session` value from the redirect URL.
3. Paste it into `BREEZE_SESSION_TOKEN` in `.env`.
4. If a running process (e.g. `uvicorn`) already started with the old
   token, restart it — the session is cached for the process lifetime, so
   an `.env` edit alone won't pick up the refreshed token. The token
   expires at midnight regardless.

If you see `BreezeAuthError` at runtime, this daily refresh is almost
always the cause.

## 4. Train the Forecasting agent's model (optional, recommended)

The Forecasting agent returns `WAIT` for every call until a model exists:

```bash
python scripts/train_forecasting_model.py
```

Pulls 180 days of 5-minute OHLCV per watchlist symbol via Breeze, builds
lagged/indicator/volatility features, and trains a LightGBM classifier,
writing `data/models/forecasting_lgbm.txt` and
`data/models/forecasting_meta.json`. Re-run periodically as more history
accumulates.

## 5. Run the backend

```bash
uvicorn backend.committee.api.main:app --reload --port 8000
```

This creates `data/committee.db` (SQLite) on first run. Smoke-test it:

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/cycle/INFY
```

Full endpoint reference (session control, discovery, suggestions, reports,
etc.) is in [docs/api.md](docs/api.md).

## 6. Run the dashboard

In a second terminal:

```bash
cd frontend
npm run dev
```

Opens on `http://localhost:5173`, talking to the backend on
`127.0.0.1:8000` (CORS is pre-scoped to `localhost`/`127.0.0.1` in
`api/main.py`). From the dashboard:

- **Run session** — starts a continuous watchlist loop: Opportunity
  Discovery selects the traded watchlist once at session start, then one
  evaluation pass every 5 minutes during NSE hours (09:15–15:30 IST),
  idle-polling outside them, with all open positions force-flattened the
  instant the session crosses 15:15 IST.
- **Autonomous / Manual toggle** — autonomous auto-executes every
  BUY/SELL/SWITCH; manual instead queues each as a suggestion card you
  approve, executing at a freshly re-fetched price when you click it.
- **Replay Mode** — for demoing outside market hours; plays cached
  historical bars through the identical live pipeline (same allocator,
  stop-loss, and cross-symbol comparison), with a progress bar over
  `bars_played`/`max_bars`.
- Live progress (discovering → evaluating → executing) is polled from
  `GET /session/progress` while any watchlist or replay pass is running.

## 7. Run tests

```bash
pytest backend/committee/tests
```

Covers consensus math, the debate revision pass, trust scoring, risk
verdicts (including the stop-loss), execution/cost-model, the capital
allocator, manual-mode suggestions, the Breeze client (mocked), the OHLCV
cache, forecasting feature/label construction, the P&L report, and a full
demo scenario end to end.

## 8. Compare against the baseline

```bash
python scripts/compare_baseline.py
```

Runs the committee (via Replay Mode, against cached OHLCV) side-by-side
with a plain vectorbt SMA-crossover strategy, one watchlist symbol at a
time (matched starting cash, matched cost assumptions, same stats
methodology), parallelized one symbol per worker process, and reports the
average performance delta across symbols.

## Repository layout

```
backend/committee/
  agents/          Technical, News & Sentiment, Macro, Forecasting
  api/             FastAPI app (main.py)
  audit/           P&L reporting (report.py)
  baseline/        vectorbt SMA-crossover comparison + shared stats
  config.py        every tunable constant, in one place
  consensus/       Consensus Orchestrator (Dynamic Trust Framework math)
  debate/          Debate Layer + Contrarian agent
  discovery/       Opportunity Discovery subsystem (own sub-package)
  execution/       Portfolio + NSE cost model
  llm/             Provider router + Gemini/OpenAI/Anthropic clients
  market_data/     Breeze client, OHLCV cache, news RSS ingestion
  nlp/             Headline cleaning
  orchestration/   Single-cycle + watchlist-loop + cross-symbol allocator
  persistence/     SQLAlchemy models, repository, session/engine setup
  replay/          Replay Mode (accelerated bar-by-bar playback)
  risk/            GARCH volatility + Risk Management Layer
  schemas.py       every pydantic contract every layer speaks
  tests/
  trust/           Trust score persistence + influence-weight math
frontend/          Vite + TypeScript dashboard (no framework)
data/
  historical/      accumulating per-symbol OHLCV cache (gitignored)
  models/          trained Forecasting model artifacts (gitignored)
  news_corpus/     cached headlines per symbol (gitignored)
  committee.db     SQLite audit trail (gitignored)
docs/              detailed architecture/agents/API/setup documentation
reports/           generated business/technical briefing exports
scripts/           train_forecasting_model.py, compare_baseline.py
```

## Further reading

- **[docs/architecture.md](docs/architecture.md)** — system design, data flow, module map
- **[docs/agents.md](docs/agents.md)** — per-agent specs (inputs, logic, outputs, failure behavior)
- **[docs/api.md](docs/api.md)** — full REST API reference
- **[docs/setup.md](docs/setup.md)** — the long-form version of the steps above
