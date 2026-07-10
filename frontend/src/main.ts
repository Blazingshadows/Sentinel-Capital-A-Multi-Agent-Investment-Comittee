import "./style.css";
import { api } from "./api";
import {
  renderCashLedger,
  renderDecisionDetail,
  renderDecisionsTable,
  renderExecutionResult,
  renderProgressPanel,
  renderStatTiles,
  renderSuggestions,
  renderTradesTable,
} from "./components";
import { renderPortfolioChart } from "./charts/portfolioChart";
import type { DecisionRow, ExecutionMode, SuggestionExecuteResult } from "./types";

// Manual mode gives judges the human-in-the-loop control they asked for:
// actionable committee decisions wait for an Execute click instead of
// auto-executing. Replay's default seconds_per_tick=0 races the demo
// through as fast as possible, which leaves no real think time before the
// next tick supersedes a symbol's suggestion -- so manual-mode replay runs
// slower on purpose (see api.main's /replay/run docstring).
const MANUAL_REPLAY_SECONDS_PER_TICK = 20;

const app = document.querySelector<HTMLDivElement>("#app")!;
app.innerHTML = `
  <header class="app-header">
    <div>
      <h1>Autonomous Multi-Agent Investment Committee</h1>
      <p>Live decisions, portfolio performance, and full committee reasoning.</p>
    </div>
    <div class="controls">
      <span class="status-line" id="status-line"></span>
      <div class="mode-toggle">
        <label><input type="radio" name="execution-mode" value="autonomous" checked /> Autonomous</label>
        <label title="Actionable decisions wait for an Execute click instead of auto-executing">
          <input type="radio" name="execution-mode" value="manual" /> Manual
        </label>
      </div>
      <button id="live-session-toggle" title="Runs continuously -- one pass every few minutes -- until you click Stop or the 15:15 IST square-off boundary is crossed">Run session</button>
      <button id="run-replay" title="Plays cached historical bars through the exact same pipeline -- for demos outside market hours">Run demo (replay)</button>
      <button id="square-off" title="Force-closes every open position right now, same as the automatic end-of-day close">Square off all</button>
    </div>
  </header>

  <div class="progress-panel hidden" id="progress-panel"></div>

  <section>
    <h2>Pending suggestions</h2>
    <p class="section-subtitle">Manual-mode decisions awaiting an execute click. Superseded by that symbol's next cycle, not a timer.</p>
    <div class="execution-result hidden" id="execution-result"></div>
    <div class="suggestions-grid" id="suggestions-panel"></div>
  </section>

  <section>
    <h2>Portfolio</h2>
    <div class="stat-tiles" id="stat-tiles"></div>
  </section>

  <section>
    <h2>Portfolio value over time</h2>
    <div class="chart-card" id="portfolio-chart"></div>
  </section>

  <section>
    <h2>Watchlist decisions</h2>
    <div class="table-card" id="decisions-table"></div>
    <div id="decision-detail"></div>
  </section>

  <section>
    <h2>Cash ledger</h2>
    <p class="section-subtitle">Raw broker cash, broken down by the trades that built it up. Not the same as buying power above.</p>
    <div class="table-card" id="cash-ledger"></div>
  </section>

  <section>
    <h2>Trade log</h2>
    <div class="table-card" id="trades-table"></div>
  </section>
`;

const progressPanelEl = document.querySelector<HTMLDivElement>("#progress-panel")!;
const suggestionsPanelEl = document.querySelector<HTMLDivElement>("#suggestions-panel")!;
const executionResultEl = document.querySelector<HTMLDivElement>("#execution-result")!;
const statTilesEl = document.querySelector<HTMLDivElement>("#stat-tiles")!;
const chartEl = document.querySelector<HTMLDivElement>("#portfolio-chart")!;
const decisionsTableEl = document.querySelector<HTMLDivElement>("#decisions-table")!;
const decisionDetailEl = document.querySelector<HTMLDivElement>("#decision-detail")!;
const cashLedgerEl = document.querySelector<HTMLDivElement>("#cash-ledger")!;
const tradesTableEl = document.querySelector<HTMLDivElement>("#trades-table")!;
const statusLineEl = document.querySelector<HTMLSpanElement>("#status-line")!;
const liveToggleButton = document.querySelector<HTMLButtonElement>("#live-session-toggle")!;
const replayButton = document.querySelector<HTMLButtonElement>("#run-replay")!;
const squareOffButton = document.querySelector<HTMLButtonElement>("#square-off")!;
const modeInputs = document.querySelectorAll<HTMLInputElement>('input[name="execution-mode"]');

let decisions: DecisionRow[] = [];
let selectedDecision: DecisionRow | null = null;
const executingSymbols = new Set<string>();

// Phases that mean a live session (POST /session/start) has actually ended --
// "idle" recurs between passes while still live, so it's deliberately not here.
const LIVE_SESSION_TERMINAL_PHASES = new Set(["stopped", "market_closed", "error"]);
let liveSessionActive = false;
let liveProgressTimer: number | null = null;
let liveRefreshTimer: number | null = null;

function currentExecutionMode(): ExecutionMode {
  return (Array.from(modeInputs).find((input) => input.checked)?.value as ExecutionMode) ?? "autonomous";
}

async function pollSuggestions(): Promise<void> {
  try {
    const suggestions = await api.suggestions();
    renderSuggestions(suggestionsPanelEl, suggestions, executeSuggestion, executingSymbols);
  } catch {
    // Transient poll failure -- next tick will retry; not worth surfacing.
  }
}

async function executeSuggestion(symbol: string): Promise<void> {
  executingSymbols.add(symbol);
  await pollSuggestions();
  try {
    const result: SuggestionExecuteResult = await api.executeSuggestion(symbol);
    renderExecutionResult(executionResultEl, { ...result, symbol });
    await refresh();
  } catch (error) {
    statusLineEl.textContent = `Execute failed for ${symbol}: ${(error as Error).message}`;
  } finally {
    executingSymbols.delete(symbol);
    await pollSuggestions();
  }
}

function selectDecision(row: DecisionRow): void {
  selectedDecision = row;
  renderDecisionsTable(decisionsTableEl, decisions, selectDecision, selectedDecision.id);
  renderDecisionDetail(decisionDetailEl, selectedDecision);
}

async function refresh(): Promise<void> {
  const [portfolio, curve, report, decisionRows, trades] = await Promise.all([
    api.portfolio(),
    api.portfolioCurve(),
    api.report(),
    api.decisions(),
    api.trades(),
  ]);

  decisions = decisionRows;
  if (selectedDecision) {
    selectedDecision = decisions.find((d) => d.id === selectedDecision!.id) ?? null;
  }

  renderStatTiles(statTilesEl, portfolio, report);
  renderPortfolioChart(chartEl, curve);
  renderDecisionsTable(decisionsTableEl, decisions, selectDecision, selectedDecision?.id ?? null);
  renderDecisionDetail(decisionDetailEl, selectedDecision);
  renderCashLedger(cashLedgerEl, trades, report.base_capital, report.current_cash);
  renderTradesTable(tradesTableEl, trades);
}

async function init(): Promise<void> {
  try {
    await api.health();
    statusLineEl.textContent = "Connected";
  } catch {
    statusLineEl.textContent = "Backend unreachable — start uvicorn on port 8000";
    return;
  }
  await refresh();
  await pollSuggestions();
  // Pending suggestions can outlive the run that created them (they're only
  // cleared by that symbol's next cycle or an execute click) -- so this
  // polls continuously, independent of whether a run is currently active.
  window.setInterval(pollSuggestions, 3_000);

  // A live session survives a page reload (it's a server-side background
  // task) -- resume polling instead of the dashboard looking idle while one
  // is actually still running underneath it.
  try {
    const progress = await api.sessionProgress();
    if (progress.mode === "live" && !LIVE_SESSION_TERMINAL_PHASES.has(progress.phase)) {
      liveSessionActive = true;
      liveToggleButton.textContent = "Stop session";
      setModeControlsDisabled(true);
      renderProgressPanel(progressPanelEl, progress);
      beginLiveSessionPolling();
    }
  } catch {
    // Backend unreachable already surfaced above.
  }
}

// Both a watchlist cycle and a replay session run for real (real Breeze
// fetches, real LLM calls per symbol) -- from seconds to several minutes,
// not instant. Rather than the dashboard looking frozen for the whole
// call, this polls GET /session/progress every second (screener stage,
// symbol currently being evaluated, tick count) and does a full refresh()
// every few seconds so decisions/trades/the value-over-time chart visibly
// update as each trade lands (see loop.run_watchlist_once's per-trade
// snapshot).
async function runWithProgress(action: () => Promise<unknown>, label: string): Promise<void> {
  liveToggleButton.disabled = true;
  replayButton.disabled = true;
  statusLineEl.textContent = label;

  const progressTimer = window.setInterval(async () => {
    try {
      renderProgressPanel(progressPanelEl, await api.sessionProgress());
    } catch {
      // Transient poll failure -- next tick will retry; not worth surfacing.
    }
  }, 1_000);
  const refreshTimer = window.setInterval(() => {
    refresh();
    pollSuggestions();
  }, 3_000);

  try {
    await action();
    statusLineEl.textContent = `${label} complete: ${new Date().toLocaleTimeString("en-IN")}`;
  } catch (error) {
    statusLineEl.textContent = `${label} failed: ${(error as Error).message}`;
  } finally {
    window.clearInterval(progressTimer);
    window.clearInterval(refreshTimer);
    try {
      renderProgressPanel(progressPanelEl, await api.sessionProgress());
    } catch {
      renderProgressPanel(progressPanelEl, null);
    }
    await refresh();
    await pollSuggestions();
    liveToggleButton.disabled = false;
    replayButton.disabled = false;
  }
}

function setModeControlsDisabled(disabled: boolean): void {
  modeInputs.forEach((input) => (input.disabled = disabled));
  replayButton.disabled = disabled;
}

// A live session (POST /session/start) is a fire-and-forget background task
// on the server -- unlike a one-shot watchlist/replay pass, this call
// returns immediately while the session keeps running for minutes to hours.
// So instead of runWithProgress's "poll until the single awaited call
// resolves" pattern, this polls indefinitely until the session itself
// reports a terminal phase (user-stopped, market-closed, or error).
function beginLiveSessionPolling(): void {
  liveProgressTimer = window.setInterval(async () => {
    try {
      const progress = await api.sessionProgress();
      renderProgressPanel(progressPanelEl, progress);
      if (progress.mode === "live" && LIVE_SESSION_TERMINAL_PHASES.has(progress.phase)) {
        const closedByMarket = progress.phase === "market_closed";
        await endLiveSession(closedByMarket ? (progress.detail ?? "Market closed.") : undefined);
      }
    } catch {
      // Transient poll failure -- next tick will retry; not worth surfacing.
    }
  }, 1_000);
  liveRefreshTimer = window.setInterval(() => {
    refresh();
    pollSuggestions();
  }, 3_000);
}

function stopLiveSessionPolling(): void {
  if (liveProgressTimer !== null) window.clearInterval(liveProgressTimer);
  if (liveRefreshTimer !== null) window.clearInterval(liveRefreshTimer);
  liveProgressTimer = null;
  liveRefreshTimer = null;
}

async function endLiveSession(statusOverride?: string): Promise<void> {
  stopLiveSessionPolling();
  liveSessionActive = false;
  liveToggleButton.textContent = "Run session";
  liveToggleButton.disabled = false;
  setModeControlsDisabled(false);
  await refresh();
  await pollSuggestions();
  statusLineEl.textContent = statusOverride ?? `Live session stopped: ${new Date().toLocaleTimeString("en-IN")}`;
}

async function startLiveSession(): Promise<void> {
  const mode = currentExecutionMode();
  liveToggleButton.disabled = true;
  statusLineEl.textContent = `Starting live session (${mode})…`;
  try {
    await api.startLiveSession(mode);
  } catch (error) {
    statusLineEl.textContent = `Failed to start live session: ${(error as Error).message}`;
    liveToggleButton.disabled = false;
    return;
  }
  liveSessionActive = true;
  liveToggleButton.textContent = "Stop session";
  liveToggleButton.disabled = false;
  setModeControlsDisabled(true);
  statusLineEl.textContent = `Live session running (${mode}) — trading Discovery's top-ranked watchlist every few minutes until stopped or 15:15 IST.`;
  beginLiveSessionPolling();
}

liveToggleButton.addEventListener("click", async () => {
  if (!liveSessionActive) {
    await startLiveSession();
    return;
  }
  liveToggleButton.disabled = true;
  statusLineEl.textContent = "Stopping live session…";
  try {
    await api.stopLiveSession();
  } catch (error) {
    statusLineEl.textContent = `Failed to stop live session cleanly: ${(error as Error).message}`;
  }
  await endLiveSession();
});

replayButton.addEventListener("click", () => {
  const mode = currentExecutionMode();
  const secondsPerTick = mode === "manual" ? MANUAL_REPLAY_SECONDS_PER_TICK : undefined;
  runWithProgress(() => api.runReplay(20, mode, secondsPerTick), `Replaying cached bars (${mode})…`);
});

squareOffButton.addEventListener("click", async () => {
  if (!confirm("Force-close every open position right now?")) return;
  squareOffButton.disabled = true;
  statusLineEl.textContent = "Squaring off all positions…";
  try {
    await api.squareOff();
    await refresh();
    statusLineEl.textContent = `Square-off complete: ${new Date().toLocaleTimeString("en-IN")}`;
  } catch (error) {
    statusLineEl.textContent = `Square-off failed: ${(error as Error).message}`;
  } finally {
    squareOffButton.disabled = false;
  }
});

window.addEventListener("resize", () => {
  if (decisions.length > 0 || chartEl.childElementCount > 0) {
    api.portfolioCurve().then((curve) => renderPortfolioChart(chartEl, curve));
  }
});

init();
