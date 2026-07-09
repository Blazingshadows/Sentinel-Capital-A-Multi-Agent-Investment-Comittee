# Agent Specs

Per-agent reference: inputs, decision logic, outputs, and failure behavior.
For how agents fit together (Debate -> Consensus -> Risk), see
`docs/architecture.md`. All specialist agents return a `schemas.AgentOutput`
(`agent`, `decision`, `confidence` in `[0,1]`, `reasoning`, `evidence`) —
that shape is what the rest of the pipeline consumes; nothing downstream
knows or cares how a given agent computed it.

## Technical Analyst Agent

`backend/committee/agents/technical.py` — `AGENT_NAME = "Technical"`

Pure pandas/numpy over OHLCV. No LLM call, no network.

**Inputs:** `context.ohlcv["Close"]` (needs ≥50 bars; below that it returns
a `WAIT`, confidence 0, "insufficient history").

**Logic:** four weighted components summed into a `score` in `[-1, 1]`:

| Component | Weight | Signal |
|---|---|---|
| RSI(14) | 0.3 | `< 30` → +weight (oversold/bullish), `> 70` → −weight (overbought/bearish), else neutral |
| EMA20 vs EMA50 cross | 0.3 | fast > slow → +weight (bullish), else −weight |
| MACD(12,26,9) histogram | 0.2 | positive → +weight, negative → −weight |
| Momentum (10-bar % change × 4, clamped to ±0.2) | 0.2 | continuous |

`decision = BUY if score > 0.15, SELL if score < -0.15, else WAIT`.
`confidence = round(abs(score), 2)`. `evidence` lists each component's raw
value (e.g. `"RSI=28.4 (oversold)"`).

`compute_rsi`, `compute_ema`, `compute_macd`, `compute_momentum` are
imported directly by the Forecasting agent, so indicator math has exactly
one implementation across the codebase.

## News & Sentiment Agent

`backend/committee/agents/news_sentiment.py` — `AGENT_NAME = "News & Sentiment"`

LLM-backed (provider: **Gemini**, via `config.AGENT_PROVIDER_MAP`).

**Inputs:** `context.headlines` — RSS-sourced headlines
(`market_data/news.py`, MoneyControl + Economic Times feeds, filtered by a
per-symbol company-alias table so "TCS" also matches "Tata Consultancy"),
cleaned via `nlp/preprocess.clean_headlines`.

**Logic:** if no relevant headlines survive, returns `WAIT`/0
confidence/"No relevant headlines found this cycle" without calling the
LLM. Otherwise sends the headline list to Gemini with a system prompt
framing it as the committee's News & Sentiment Analyst, asking for
BUY/SELL/WAIT + confidence + reasoning + evidence citing specific headlines,
validated against `schemas.LLMAgentVerdict`.

**Degradation:** on `LLMUnavailableError` (no API key, or the model failed
structured-output validation twice), returns `WAIT`/0 confidence with the
error message in `reasoning` and the first 3 raw headlines as evidence —
never crashes the cycle.

## Macro Analyst Agent

`backend/committee/agents/macro.py` — `AGENT_NAME = "Macro"`

LLM-backed (provider: **OpenAI**).

**Inputs:** `context.sector`, `context.fundamentals["marketCap"]` (from
`config.WATCHLIST_FUNDAMENTALS`, a static table — Breeze has no
fundamentals/sector endpoint), and `context.context_flags` (e.g.
`earnings_day`, `rbi_policy_day`, `normal`).

**Logic:** sends sector, market cap, and active context flags to the LLM
with a system prompt scoping it to sector/macro/policy factors specifically
— explicitly *not* company-specific news (News & Sentiment's job) or price
action (Technical's job) — asking for BUY/SELL/WAIT + confidence + evidence
of the macro factors weighed.

**Degradation:** same pattern as News & Sentiment — `WAIT`/0 confidence with
`sector=...`/`context_flags=...` as evidence on LLM failure.

## Forecasting Agent

`backend/committee/agents/forecasting.py` — `AGENT_NAME = "Forecasting"`

Not an LLM call — a LightGBM multiclass classifier, trained offline. This is
the deliberately "different point of view" specialist: pattern-matching on
lagged price/volume features rather than language-based reasoning.

**Model:** loaded lazily from `data/models/forecasting_lgbm.txt` +
`data/models/forecasting_meta.json` (feature importances), trained by
`scripts/train_forecasting_model.py`. If no model file exists yet, returns
`WAIT`/0 confidence with a pointer to run the training script — never
crashes the cycle on a missing model.

**Features** (`build_features`, shared verbatim between training and
inference so the model always sees what it was trained on):

- `lag_return_{1,2,3,5,10}` — pct-change over each lag period
- `rsi_14` — RSI scaled to `[0,1]`
- `macd_hist` — MACD histogram normalized by price
- `ema_diff` — `(EMA20 - EMA50) / EMA50`
- `volatility` — rolling 10-bar std of returns
- `volume_change` — pct-change in volume

**Labels** (`build_labels`, training-time only): 3-class
{bearish=-1, neutral=0, bullish=1} over the forward return
`FORECAST_LOOKAHEAD_BARS` bars ahead (9 bars × 5min ≈ 45min horizon). The
bullish/bearish threshold is a **volatility-scaled deadzone**, not a fixed
return: `deadzone = clip(FORECAST_DEADZONE_VOL_MULTIPLIER × horizon_vol,
min=FORECAST_DEADZONE_MIN_RETURN)`, where `horizon_vol` scales the stock's
own rolling per-bar volatility by `sqrt(lookahead)` (variance scales with
time under a random-walk assumption). A flat threshold would mislabel a
calm stock's noise as a real move and a volatile stock's real moves as
noise when pooled together for training; the floor keeps a near-zero rolling
vol (a dead market open) from collapsing the deadzone to ~0.

**Inference:** predicts `[P(bearish), P(neutral), P(bullish)]` on the latest
bar's features; `decision` = argmax class, `confidence` = that class's
probability. If any feature is `NaN` (insufficient history this cycle),
returns `WAIT`/0. `evidence` lists the top-3 features by trained importance
with their current values.

## Contrarian Agent

`backend/committee/debate/contrarian.py` — `AGENT_NAME = "Contrarian"`

LLM-backed (provider: **Anthropic**). Lives in `debate/`, not `agents/`,
because it plays a dual role: a normal specialist vote *and* the Debate
Layer's challenger.

**Inputs:** the other 4 agents' original (pre-debate) recommendations,
formatted as a bulleted list with each agent's decision/confidence/reasoning.

**Logic:** system prompt frames it as the committee's designated
challenger — find blind spots, attack weak arguments in the *leading*
proposal (highest-confidence recommendation among the others), surface
alternative interpretations — then cast its own BUY/SELL/WAIT vote with
justified confidence, validated against `schemas.ContrarianVerdict` (adds
`challenge: str` and `risk_observations: list[str]` on top of the standard
verdict fields).

**Output:** `ContrarianVerdict.to_agent_output()` converts it into the same
`AgentOutput` shape as every other specialist for consensus purposes; the
`challenge`/`risk_observations` feed `DebateResult` separately and drive the
Debate Layer's confidence-revision pass (see `docs/architecture.md` §Debate
Layer).

**Degradation:** on LLM failure, returns `WAIT`/0 confidence, an empty
challenge string, and no risk observations — the revision pass then damps
nothing (a WAIT contrarian never disagrees directionally with anyone).

## Opportunity Discovery Agent

`backend/committee/discovery/agent.py` — `OpportunityDiscoveryAgent`. Not
part of the per-symbol committee cycle above; it's a separate,
upstream stage that narrows the ~300-symbol NSE universe down to the
~50-60 highest-opportunity names, and emits **no directional call and no
forecast** — only a relative "how worth looking at is this name" ranking.
See `docs/architecture.md` §Opportunity Discovery subsystem for how the
three stages compose. Config for every threshold/weight lives in
`backend/committee/discovery/config.py` (`DiscoveryConfig`, overridable via
`discovery/config/default_config.json`).

### Stage 1 — Market Scanner (`scanner.py`, `MarketScannerAgent`)

High-recall pre-screen: only removes obviously-untradeable names (no
history, illiquid, penny price, degenerate/flat data). Computes one
`SymbolScan` metric bundle per symbol (reused by scoring, so nothing is
computed twice):

- `atr_pct`, `hist_volatility` (annualized), `adx` (kept for explainability)
- `relative_volume` — recent-window mean volume vs. trailing median
- `momentum` (blended multi-horizon) and `risk_adj_momentum`
  (information-ratio momentum: per-horizon return / expected vol)
- `trend_efficiency` — Kaufman efficiency ratio, `|net move| / path length`
- `trend_slope` — normalized fast/slow EMA spread
- `gap_pct`, `vol_expansion_ratio` (short-window vol / long-window vol),
  `ema_stretch` (distance from EMA in ATR units), `range_position`
  (`[0,1]`, proximity to the recent high/low)

Also labels the market **regime** (`RISK_ON`/`RISK_OFF`/`NEUTRAL`/
`HIGH_VOLATILITY`/`UNKNOWN`, from cross-sectional breadth + median ATR%) and
**cross-sectional dispersion** (MAD of survivor risk-adjusted momentum — how
much stock-picking-rich spread there is this cycle).

### Stage 2 — Opportunity Scoring (`scoring.py`, `OpportunityScoringAgent`)

Turns each survivor's raw metrics into an explainable composite score:

1. **Robust standardization** — median/MAD z-scores with soft-winsor
   (`tanh`, preserves tail ordering instead of hard-clipping the biggest
   movers, which are exactly the names discovery exists to surface).
2. **Decorrelation weighting** (optional, on by default) — each factor's
   base weight is divided by its summed absolute correlation with the rest
   of the panel *this cycle*, then rescaled to preserve total weight. Keeps
   the momentum family (momentum/relative-strength/trend/sector) from being
   counted four times when they're all pointing the same way.
3. **11 factors** (`FactorScores`): `liquidity`, `trend_quality`,
   `relative_strength`, `momentum`, `mean_reversion`, `breakout`,
   `volume_expansion`, `volatility_opportunity`, `sector_strength`, `event`,
   and `risk_penalty` (subtracted). Two-sided factors (momentum,
   relative_strength, mean_reversion, breakout) contribute by `|z|` — a big
   move either way is opportunity.
4. **Composite → percentile** — summed weighted contributions, converted to
   a 0–100 cross-sectional percentile (`opportunity_score`).
5. **Confidence** — weighted geometric mean of four components:
   data completeness, statistical significance (composite's own percentile
   rank), signed cross-factor agreement, and jackknife stability
   (leave-one-factor-out: does the name survive in the top-K without each
   factor?).
6. **Capacity score** — percentile of log(median turnover) — a deployable-
   size proxy, since for a large book opportunity value is edge × capacity.

Every candidate carries `factor_contributions`, `contribution_pct`,
`confidence_breakdown`, and a human-readable `reasoning` list — fully
explainable, not just a number.

### Stage 3 — Diversity Optimizer (`diversity.py`, `DiversityOptimizerAgent`)

De-duplicates the scored pool down to a target 50–60 names via greedy
submodular selection (carries the classic `(1 - 1/e)` approximation
guarantee):

- **Sector cap** — no sector exceeds `max_per_sector_fraction` (30%) of the
  list.
- **Correlation clustering** on Ledoit-Wolf shrunk covariance (a raw
  60-bar sample correlation over ~150 names is badly rank-deficient and
  invents spurious clusters) — at most `max_per_correlation_cluster` (3)
  names survive per cluster; falls back to sector-based clustering if
  return series are unavailable.
- **Similarity penalty** — marginal value of adding a candidate is damped by
  its overlap with already-selected names in the same cluster.
- **Capacity tilt** — marginal value scaled by a bounded function of the
  candidate's capacity score.
- **Recall top-up** — if caps leave the list below `target_min` (50), the
  highest-scoring remaining names are added regardless of caps, flagged as
  such in `selection_explanation`.

### Data provider

`discovery/data_provider.py`: `LiveMarketDataProvider` wraps the existing
`market_data.prices.fetch_ohlcv` (Breeze) with a bounded parallel
(`ThreadPoolExecutor`) batch fetch and per-symbol fault tolerance — one bad
symbol never aborts the batch. `InMemoryDataProvider` is a deterministic,
network-free stand-in used by tests. Sector comes from the discovery
universe asset (`universe/nse_universe.json`), never a live call, since
Breeze has no sector endpoint.
