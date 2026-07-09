import type { DecisionRow, PortfolioSnapshotRow, PortfolioState, ReportSummary, TradeRow } from "./types";

const BASE_URL = "http://127.0.0.1:8000";

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

type WatchlistStreamEvent =
  | { type: "progress"; message: string }
  | { type: "done"; decisions: DecisionRow[] }
  | { type: "error"; message: string };

/** Streams newline-delimited JSON progress events from `/watchlist/run/stream`
 * as they arrive, so the UI can show per-symbol/per-agent status instead of
 * a single blocking spinner for the whole (multi-minute) pass. */
async function runWatchlistStream(onEvent: (event: WatchlistStreamEvent) => void): Promise<DecisionRow[]> {
  const response = await fetch(`${BASE_URL}/watchlist/run/stream`, { method: "POST" });
  if (!response.ok || !response.body) throw new Error(`/watchlist/run/stream -> ${response.status}`);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let newlineIndex: number;
    while ((newlineIndex = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (!line) continue;

      const event = JSON.parse(line) as WatchlistStreamEvent;
      onEvent(event);
      if (event.type === "done") return event.decisions;
      if (event.type === "error") throw new Error(event.message);
    }
  }

  throw new Error("/watchlist/run/stream ended without a completion event");
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
  runWatchlistStream,
};
