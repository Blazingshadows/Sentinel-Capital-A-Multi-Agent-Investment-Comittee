import "./style.css";
import { api } from "./api";
import { renderDecisionDetail, renderDecisionsTable, renderStatTiles, renderTradesTable } from "./components";
import { renderPortfolioChart } from "./charts/portfolioChart";
import type { DecisionRow } from "./types";

const app = document.querySelector<HTMLDivElement>("#app")!;
app.innerHTML = `
  <header class="app-header">
    <div>
      <h1>Autonomous Multi-Agent Investment Committee</h1>
      <p>Live decisions, portfolio performance, and full committee reasoning.</p>
    </div>
    <div class="controls">
      <span class="status-line" id="status-line"></span>
      <button id="run-watchlist">Run watchlist cycle</button>
    </div>
  </header>

  <section id="progress-section" class="progress-section" hidden>
    <h2>Run progress</h2>
    <div class="progress-log" id="progress-log"></div>
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
    <h2>Trade log</h2>
    <div class="table-card" id="trades-table"></div>
  </section>
`;

const statTilesEl = document.querySelector<HTMLDivElement>("#stat-tiles")!;
const chartEl = document.querySelector<HTMLDivElement>("#portfolio-chart")!;
const decisionsTableEl = document.querySelector<HTMLDivElement>("#decisions-table")!;
const decisionDetailEl = document.querySelector<HTMLDivElement>("#decision-detail")!;
const tradesTableEl = document.querySelector<HTMLDivElement>("#trades-table")!;
const statusLineEl = document.querySelector<HTMLSpanElement>("#status-line")!;
const runButton = document.querySelector<HTMLButtonElement>("#run-watchlist")!;
const progressSectionEl = document.querySelector<HTMLElement>("#progress-section")!;
const progressLogEl = document.querySelector<HTMLDivElement>("#progress-log")!;

function appendProgressLine(message: string, tone: "info" | "error" = "info"): void {
  const line = document.createElement("div");
  line.className = `progress-log-line ${tone}`;
  line.textContent = message;
  progressLogEl.appendChild(line);
  progressLogEl.scrollTop = progressLogEl.scrollHeight;
}

let decisions: DecisionRow[] = [];
let selectedDecision: DecisionRow | null = null;

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
}

runButton.addEventListener("click", async () => {
  runButton.disabled = true;
  progressLogEl.innerHTML = "";
  progressSectionEl.hidden = false;
  statusLineEl.textContent = "Running watchlist cycle…";
  try {
    await api.runWatchlistStream((event) => {
      if (event.type === "progress") {
        appendProgressLine(event.message);
        statusLineEl.textContent = event.message;
      } else if (event.type === "error") {
        appendProgressLine(event.message, "error");
      }
    });
    await refresh();
    statusLineEl.textContent = `Last run: ${new Date().toLocaleTimeString("en-IN")}`;
  } catch (error) {
    appendProgressLine((error as Error).message, "error");
    statusLineEl.textContent = `Run failed: ${(error as Error).message}`;
  } finally {
    runButton.disabled = false;
  }
});

window.addEventListener("resize", () => {
  if (decisions.length > 0 || chartEl.childElementCount > 0) {
    api.portfolioCurve().then((curve) => renderPortfolioChart(chartEl, curve));
  }
});

init();
