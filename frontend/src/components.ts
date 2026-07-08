import { formatCurrency } from "./format";
import type { DecisionRow, PortfolioState, ReportSummary, TradeRow } from "./types";

function badge(decision: string): HTMLElement {
  const span = document.createElement("span");
  const cls = decision === "BUY" ? "buy" : decision === "SELL" ? "sell" : "wait";
  span.className = `badge ${cls}`;
  span.textContent = decision;
  return span;
}

export function renderStatTiles(container: HTMLElement, portfolio: PortfolioState, report: ReportSummary): void {
  const positionCount = Object.values(portfolio.positions).filter((qty) => qty !== 0).length;

  const tiles: { label: string; value: string; delta?: { text: string; positive: boolean } }[] = [
    { label: "Starting value", value: formatCurrency(report.starting_value) },
    { label: "Starting cash", value: formatCurrency(report.starting_cash) },
    { label: "Current value", value: formatCurrency(report.portfolio_value) },
    { label: "Current cash", value: formatCurrency(report.current_cash) },
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
