import { formatCurrency } from "./format";
import type { DecisionRow, PortfolioState, ReportSummary, SessionProgress, TradeRow } from "./types";

const BADGE_CLASS: Record<string, string> = {
  BUY: "buy",
  SELL: "sell",
  HOLD: "hold",
  WAIT: "wait",
  SWITCH: "switch",
};

function badge(decision: string): HTMLElement {
  const span = document.createElement("span");
  span.className = `badge ${BADGE_CLASS[decision] ?? "wait"}`;
  span.textContent = decision;
  return span;
}

const PHASE_LABEL: Record<string, string> = {
  idle: "Idle",
  starting: "Starting…",
  discovering: "Screening universe…",
  evaluating: "Evaluating…",
  executing: "Executing trades…",
  error: "Error",
};

/** Live status of a running /watchlist/run or /replay/run pass, polled from
 * GET /session/progress -- gives the dashboard a pulse (stocks loaded,
 * screener narrowing the universe, which symbol is being evaluated right
 * now) instead of looking frozen for however long a full pass takes. */
export function renderProgressPanel(container: HTMLElement, progress: SessionProgress | null): void {
  container.innerHTML = "";

  if (!progress || (progress.phase === "idle" && !progress.mode)) {
    container.classList.add("hidden");
    return;
  }
  container.classList.remove("hidden");

  const header = document.createElement("div");
  header.className = "progress-header";

  const phaseEl = document.createElement("span");
  phaseEl.className = `progress-phase phase-${progress.phase}`;
  phaseEl.textContent = PHASE_LABEL[progress.phase] ?? progress.phase;
  header.appendChild(phaseEl);

  if (progress.mode) {
    const modeEl = document.createElement("span");
    modeEl.className = "progress-mode";
    modeEl.textContent = progress.mode === "replay" ? "Replay demo" : "Watchlist cycle";
    header.appendChild(modeEl);
  }

  const detailEl = document.createElement("span");
  detailEl.className = "progress-detail";
  detailEl.textContent = progress.detail ?? "";
  header.appendChild(detailEl);

  container.appendChild(header);

  if (progress.watchlist && progress.watchlist.length > 0) {
    const discoveryLine = document.createElement("div");
    discoveryLine.className = "progress-discovery";
    discoveryLine.textContent =
      `${progress.universe_size ?? "?"} stocks loaded -> ${progress.survived_scan ?? "?"} passed the screen -> ` +
      `${progress.selected_count ?? "?"} scored & diversified -> trading top ${progress.watchlist.length}: ` +
      progress.watchlist.join(", ");
    container.appendChild(discoveryLine);
  }

  if (progress.symbols_total) {
    const completed = progress.symbols_completed ?? 0;
    const pct = progress.symbols_total > 0 ? (completed / progress.symbols_total) * 100 : 0;

    const track = document.createElement("div");
    track.className = "progress-bar-track";
    const fill = document.createElement("div");
    fill.className = "progress-bar-fill";
    fill.style.width = `${pct}%`;
    track.appendChild(fill);
    container.appendChild(track);

    const label = document.createElement("div");
    label.className = "progress-bar-label";
    label.textContent = progress.current_symbol
      ? `${progress.current_symbol} (${completed}/${progress.symbols_total})`
      : `${completed}/${progress.symbols_total} symbols`;
    container.appendChild(label);
  }

  if (progress.max_bars) {
    const barsPlayed = progress.bars_played ?? 0;
    const pct = progress.max_bars > 0 ? (barsPlayed / progress.max_bars) * 100 : 0;

    const track = document.createElement("div");
    track.className = "progress-bar-track";
    const fill = document.createElement("div");
    fill.className = "progress-bar-fill replay";
    fill.style.width = `${pct}%`;
    track.appendChild(fill);
    container.appendChild(track);

    const label = document.createElement("div");
    label.className = "progress-bar-label";
    label.textContent = `Replay tick ${barsPlayed}/${progress.max_bars}`;
    container.appendChild(label);
  }
}

export function renderStatTiles(container: HTMLElement, portfolio: PortfolioState, report: ReportSummary): void {
  const positionCount = Object.values(portfolio.positions).filter((qty) => qty !== 0).length;

  const tiles: { label: string; value: string; delta?: { text: string; positive: boolean } }[] = [
    { label: "Base capital", value: formatCurrency(report.base_capital) },
    { label: "Base buying power", value: formatCurrency(report.base_buying_power) },
    { label: "Current capital", value: formatCurrency(report.current_capital) },
    { label: "Current buying power", value: formatCurrency(report.current_buying_power) },
    {
      label: "Net P&L",
      value: formatCurrency(report.net_pnl),
      delta: { text: `${report.growth_pct >= 0 ? "+" : ""}${report.growth_pct.toFixed(2)}%`, positive: report.net_pnl >= 0 },
    },
    { label: "Gross P&L", value: formatCurrency(report.gross_pnl) },
    { label: "Trading costs", value: formatCurrency(report.total_costs) },
    { label: "Open positions", value: String(positionCount) },
    { label: "Trades executed", value: String(report.trade_count) },
  ];

  container.innerHTML = "";
  for (const tile of tiles) {
    const el = document.createElement("div");
    el.className = "stat-tile";

    const label = document.createElement("div");
    label.className = "label";
    label.textContent = tile.label;
    el.appendChild(label);

    const value = document.createElement("div");
    value.className = "value";
    value.textContent = tile.value;
    el.appendChild(value);

    if (tile.delta) {
      const delta = document.createElement("div");
      delta.className = `delta ${tile.delta.positive ? "positive" : "negative"}`;
      delta.textContent = tile.delta.text;
      el.appendChild(delta);
    }

    container.appendChild(el);
  }
}

/** Latest decision per stock, most-recently-evaluated symbols first. */
function latestPerStock(decisions: DecisionRow[]): DecisionRow[] {
  const latest = new Map<string, DecisionRow>();
  for (const row of decisions) {
    const existing = latest.get(row.stock);
    if (!existing || new Date(row.cycle_ts) > new Date(existing.cycle_ts)) {
      latest.set(row.stock, row);
    }
  }
  return [...latest.values()].sort((a, b) => new Date(b.cycle_ts).getTime() - new Date(a.cycle_ts).getTime());
}

export function renderDecisionsTable(
  container: HTMLElement,
  decisions: DecisionRow[],
  onSelect: (row: DecisionRow) => void,
  selectedId: number | null,
): void {
  container.innerHTML = "";

  const rows = latestPerStock(decisions);
  if (rows.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No decisions yet — run a cycle to get started.";
    container.appendChild(empty);
    return;
  }

  const table = document.createElement("table");
  table.innerHTML =
    "<thead><tr><th>Stock</th><th>Consensus</th><th>Confidence</th><th>Risk</th><th>Action</th><th>Time</th></tr></thead>";
  const tbody = document.createElement("tbody");

  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.className = "clickable";
    if (row.id === selectedId) tr.classList.add("selected");
    tr.addEventListener("click", () => onSelect(row));

    const stockCell = document.createElement("td");
    stockCell.textContent = row.stock;
    tr.appendChild(stockCell);

    const decisionCell = document.createElement("td");
    decisionCell.appendChild(badge(row.consensus_decision));
    tr.appendChild(decisionCell);

    const confidenceCell = document.createElement("td");
    confidenceCell.textContent = row.consensus_confidence.toFixed(2);
    tr.appendChild(confidenceCell);

    const riskCell = document.createElement("td");
    riskCell.textContent = row.risk_action;
    tr.appendChild(riskCell);

    const actionCell = document.createElement("td");
    actionCell.appendChild(badge(row.action_taken));
    tr.appendChild(actionCell);

    const timeCell = document.createElement("td");
    timeCell.textContent = new Date(row.cycle_ts).toLocaleTimeString("en-IN");
    tr.appendChild(timeCell);

    tbody.appendChild(tr);
  }

  table.appendChild(tbody);
  container.appendChild(table);
}

export function renderDecisionDetail(container: HTMLElement, row: DecisionRow | null): void {
  container.innerHTML = "";
  if (!row) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Select a stock above to see how the committee reached its decision.";
    container.appendChild(empty);
    return;
  }

  const heading = document.createElement("h3");
  heading.textContent = `${row.stock} — committee reasoning`;
  container.appendChild(heading);

  for (const agent of row.agent_recommendations) {
    const line = document.createElement("div");
    line.className = "agent-vote";

    const name = document.createElement("div");
    name.className = "agent-name";
    name.appendChild(badge(agent.decision));
    const nameText = document.createElement("span");
    nameText.style.marginLeft = "6px";
    nameText.textContent = agent.agent;
    name.appendChild(nameText);

    const reasoning = document.createElement("div");
    reasoning.className = "agent-reasoning";
    reasoning.textContent = agent.reasoning;

    const confidence = document.createElement("div");
    confidence.className = "agent-confidence";
    confidence.textContent = agent.confidence.toFixed(2);

    line.append(name, reasoning, confidence);
    container.appendChild(line);
  }

  if (row.debate.contrarian_challenge) {
    const challenge = document.createElement("p");
    challenge.className = "reasoning-block";
    const strong = document.createElement("strong");
    strong.textContent = "Contrarian challenge: ";
    challenge.appendChild(strong);
    challenge.appendChild(document.createTextNode(row.debate.contrarian_challenge));
    container.appendChild(challenge);
  }

  const consensus = document.createElement("p");
  consensus.className = "reasoning-block";
  const consensusLabel = document.createElement("strong");
  consensusLabel.textContent = "Consensus: ";
  consensus.appendChild(consensusLabel);
  consensus.appendChild(document.createTextNode(row.consensus_reasoning));
  container.appendChild(consensus);

  const risk = document.createElement("p");
  risk.className = "reasoning-block";
  const riskLabel = document.createElement("strong");
  riskLabel.textContent = "Risk verdict: ";
  risk.appendChild(riskLabel);
  risk.appendChild(document.createTextNode(row.risk_reason));
  container.appendChild(risk);

  const expected = document.createElement("p");
  expected.className = "reasoning-block";
  const expectedLabel = document.createElement("strong");
  expectedLabel.textContent = "Expected risk & return: ";
  expected.appendChild(expectedLabel);
  const returnPct = (row.risk_expected_return * 100).toFixed(2);
  const drawdownPct = (row.risk_expected_drawdown * 100).toFixed(2);
  expected.appendChild(
    document.createTextNode(
      `${Number(returnPct) >= 0 ? "+" : ""}${returnPct}% expected return, ${drawdownPct}% expected drawdown ` +
        `(heuristic, confidence x volatility scaled -- not a backtested figure).`,
    ),
  );
  container.appendChild(expected);

  if (row.alternatives.length > 0) {
    const altHeading = document.createElement("p");
    altHeading.className = "reasoning-block";
    const altLabel = document.createElement("strong");
    altLabel.textContent = "Alternative stocks considered: ";
    altHeading.appendChild(altLabel);
    container.appendChild(altHeading);

    for (const alt of row.alternatives) {
      const line = document.createElement("div");
      line.className = "agent-vote";
      const name = document.createElement("div");
      name.className = "agent-name";
      name.appendChild(badge(alt.decision));
      const nameText = document.createElement("span");
      nameText.style.marginLeft = "6px";
      nameText.textContent = alt.symbol;
      name.appendChild(nameText);
      const confidence = document.createElement("div");
      confidence.className = "agent-confidence";
      confidence.textContent = alt.confidence.toFixed(2);
      line.append(name, document.createElement("div"), confidence);
      container.appendChild(line);
    }
  }
}

/** Raw broker cash is a ledger balance, not equity -- shorting a stock credits
 * proceeds to cash while the position carries an offsetting negative value, so
 * cash alone drifts away from the "buying power" tile up top. This renders the
 * per-stock cash flows that add up to that ledger balance, so the number is
 * traceable instead of appearing out of nowhere. */
export function renderCashLedger(container: HTMLElement, trades: TradeRow[], baseCapital: number, currentCash: number): void {
  container.innerHTML = "";

  if (trades.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No trades yet — the ledger starts at base capital.";
    container.appendChild(empty);
    return;
  }

  const byStock = new Map<string, { tradeCount: number; netFlow: number }>();
  for (const trade of trades) {
    const entry = byStock.get(trade.stock) ?? { tradeCount: 0, netFlow: 0 };
    entry.tradeCount += 1;
    entry.netFlow += trade.net_cash_flow;
    byStock.set(trade.stock, entry);
  }

  const rows = [...byStock.entries()].sort((a, b) => Math.abs(b[1].netFlow) - Math.abs(a[1].netFlow));
  const totalFlow = rows.reduce((sum, [, entry]) => sum + entry.netFlow, 0);

  const table = document.createElement("table");
  table.innerHTML = "<thead><tr><th>Stock</th><th>Trades</th><th>Net cash flow</th></tr></thead>";
  const tbody = document.createElement("tbody");

  const startRow = document.createElement("tr");
  const startLabelCell = document.createElement("td");
  startLabelCell.textContent = "Starting cash";
  const startDashCell = document.createElement("td");
  startDashCell.textContent = "-";
  const startValueCell = document.createElement("td");
  startValueCell.textContent = formatCurrency(baseCapital);
  startRow.append(startLabelCell, startDashCell, startValueCell);
  tbody.appendChild(startRow);

  for (const [stock, entry] of rows) {
    const tr = document.createElement("tr");

    const stockCell = document.createElement("td");
    stockCell.textContent = stock;
    tr.appendChild(stockCell);

    const countCell = document.createElement("td");
    countCell.textContent = String(entry.tradeCount);
    tr.appendChild(countCell);

    const flowCell = document.createElement("td");
    flowCell.textContent = `${entry.netFlow >= 0 ? "+" : ""}${formatCurrency(entry.netFlow)}`;
    tr.appendChild(flowCell);

    tbody.appendChild(tr);
  }

  table.appendChild(tbody);

  const tfoot = document.createElement("tfoot");
  const totalRow = document.createElement("tr");
  totalRow.className = "ledger-total";
  const totalLabelCell = document.createElement("td");
  totalLabelCell.textContent = "Ledger cash balance";
  const totalCountCell = document.createElement("td");
  totalCountCell.textContent = String(trades.length);
  const totalValueCell = document.createElement("td");
  totalValueCell.textContent = formatCurrency(baseCapital + totalFlow);
  totalRow.append(totalLabelCell, totalCountCell, totalValueCell);
  tfoot.appendChild(totalRow);
  table.appendChild(tfoot);

  container.appendChild(table);

  const note = document.createElement("p");
  note.className = "ledger-note";
  note.textContent =
    "This is the broker's raw cash ledger, not spendable profit or equity. " +
    "Short sales credit proceeds here while the offsetting position value is negative, so cash can run well above " +
    `starting capital (${formatCurrency(baseCapital)}) even when the portfolio is flat. Reconciled balance: ${formatCurrency(currentCash)}.`;
  container.appendChild(note);
}

export function renderTradesTable(container: HTMLElement, trades: TradeRow[]): void {
  container.innerHTML = "";

  if (trades.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No trades executed yet.";
    container.appendChild(empty);
    return;
  }

  const table = document.createElement("table");
  table.innerHTML = "<thead><tr><th>Time</th><th>Stock</th><th>Action</th><th>Qty</th><th>Price</th><th>Costs</th><th>Net cash flow</th></tr></thead>";
  const tbody = document.createElement("tbody");

  for (const trade of [...trades].reverse()) {
    const tr = document.createElement("tr");

    const timeCell = document.createElement("td");
    timeCell.textContent = new Date(trade.ts).toLocaleTimeString("en-IN");
    tr.appendChild(timeCell);

    const stockCell = document.createElement("td");
    stockCell.textContent = trade.stock;
    tr.appendChild(stockCell);

    const actionCell = document.createElement("td");
    actionCell.appendChild(badge(trade.action));
    tr.appendChild(actionCell);

    const qtyCell = document.createElement("td");
    qtyCell.textContent = trade.qty.toString();
    tr.appendChild(qtyCell);

    const priceCell = document.createElement("td");
    priceCell.textContent = formatCurrency(trade.price);
    tr.appendChild(priceCell);

    const costCell = document.createElement("td");
    costCell.textContent = trade.cost_breakdown ? formatCurrency(trade.cost_breakdown.total_cost) : "-";
    tr.appendChild(costCell);

    const netCell = document.createElement("td");
    netCell.textContent = formatCurrency(trade.net_cash_flow);
    tr.appendChild(netCell);

    tbody.appendChild(tr);
  }

  table.appendChild(tbody);
  container.appendChild(table);
}
