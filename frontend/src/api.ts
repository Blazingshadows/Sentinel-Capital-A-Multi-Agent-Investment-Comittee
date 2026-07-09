import type { DecisionRow, PortfolioSnapshotRow, PortfolioState, ReportSummary, TradeRow } from "./types";

const BASE_URL = "http://127.0.0.1:8001";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`);
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, { method: "POST" });
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return response.json() as Promise<T>;
}

export const api = {
  health: () => getJson<{ status: string }>("/health"),
  portfolio: () => getJson<PortfolioState>("/portfolio"),
  portfolioCurve: () => getJson<PortfolioSnapshotRow[]>("/portfolio/curve"),
  decisions: (stock?: string) => getJson<DecisionRow[]>(`/decisions${stock ? `?stock=${stock}` : ""}`),
  trades: (stock?: string) => getJson<TradeRow[]>(`/trades${stock ? `?stock=${stock}` : ""}`),
  report: () => getJson<ReportSummary>("/report"),
  runCycle: (symbol: string) => postJson<{ decision: DecisionRow; price: number }>(`/cycle/${symbol}`),
  runWatchlist: () => postJson<DecisionRow[]>("/watchlist/run"),
  runReplay: (maxBars = 20) => postJson<{ status: string; max_bars: number }>(`/replay/run?max_bars=${maxBars}`),
  squareOff: () => postJson<unknown[]>("/session/square-off"),
};
