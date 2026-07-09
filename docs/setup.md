# Setup & Running Locally

## Prerequisites

- Python 3.11+
- Node.js (for the dashboard; `frontend/package.json` targets a recent Vite)
- An [ICICI Direct Breeze API](https://api.icicidirect.com/apiuser/home)
  app (required for live market data — see below)
- API keys for Gemini, OpenAI, and Anthropic (each LLM-backed agent
  degrades to a neutral WAIT if its key is missing, so the committee still
  runs without all three, just with fewer live opinions)

## Install

```bash
pip install -e ".[dev]"
```

`pyproject.toml` pulls in FastAPI, SQLAlchemy, pandas/numpy/scikit-learn,
`arch` (GARCH), `breeze-connect`, `feedparser`, `lightgbm`, `vectorbt`, and
the three LLM SDKs. `dev` adds `pytest`/`pytest-asyncio`. There's also an
optional `dl` extra (`torch`) that isn't required by anything currently
in the codebase.

For the dashboard:

```bash
cd frontend
npm install
```

## Configure `.env`

Copy `.env.example` to `.env` and fill in:

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

### Breeze daily login (required for live market data)

Breeze/ICICI Direct is a *trading* API, and SEBI requires a manual browser
login every trading day — there's no automated refresh:

1. `BREEZE_API_KEY` / `BREEZE_API_SECRET` come once from your app at
   https://api.icicidirect.com/apiuser/home ("View Apps") — these are
   static and don't need refreshing.
2. Each trading morning, log in at that same page to get a fresh
   `api_session` value from the redirect URL, and paste it into
   `BREEZE_SESSION_TOKEN`.
3. It **expires at midnight**. If you see `BreezeAuthError` at runtime,
   this is almost always why — refresh the token and restart any
   long-running process (`_get_client()` caches the authenticated session
   for the process lifetime, so a stale token requires a restart, not just
   an `.env` edit).

Without valid Breeze credentials, `market_data.prices.fetch_ohlcv` still
works off whatever's already cached in `data/historical/*.csv` from a
previous successful pull (`use_cache_on_failure=True` by default) — useful
for offline development and Replay Mode, but any symbol that's never been
fetched live will error.

## Run the backend

```bash
uvicorn backend.committee.api.main:app --reload --port 8000
```

Initializes `data/committee.db` (SQLite) on first run. See `docs/api.md`
for the full endpoint list. Quick smoke test:

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/cycle/INFY
```

## Run the dashboard

```bash
cd frontend
npm run dev
```

Opens on `http://localhost:5173`, talking to the backend on
`127.0.0.1:8000` (CORS is pre-scoped to this origin in `api/main.py`). Use
the **Run session** button to start a continuous watchlist loop (one pass
every 5 minutes during NSE hours, idle-polling outside them) — see
`POST /session/start` in `docs/api.md`.

## Train the Forecasting agent's model

The Forecasting agent returns `WAIT` until a model exists:

```bash
python scripts/train_forecasting_model.py
```

Pulls `FORECAST_TRAIN_PERIOD` (180 days) of `FORECAST_TRAIN_INTERVAL`
(5-minute) OHLCV per watchlist symbol via Breeze, builds
lagged/indicator/volatility features, trains a LightGBM classifier on a
per-symbol time-based holdout (last 20% of each symbol's bars, pooled
across symbols to avoid leaking future bars from one symbol into another's
training fold), and writes `data/models/forecasting_lgbm.txt` +
`data/models/forecasting_meta.json`. Re-run periodically as more history
accumulates.

## Run tests

```bash
pytest backend/committee/tests
```

Covers consensus math, the debate revision pass, trust scoring, risk
verdicts, execution/cost-model, the capital allocator, the Breeze client
(mocked), the OHLCV cache, forecasting feature/label construction, the P&L
report, and a full demo scenario end to end
(`backend/committee/tests/conftest.py` sets up an in-memory SQLite session
fixture used across most of these).

## Compare against the baseline

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
docs/              this documentation
reports/           generated business/technical briefing exports
scripts/           train_forecasting_model.py, compare_baseline.py
```

See `docs/architecture.md` for how these fit together and `docs/agents.md`
for what each specialist agent actually does.
