import type {
  DecisionRow,
  ExecutionMode,
  PortfolioSnapshotRow,
  PortfolioState,
  ReportSummary,
  SessionProgress,
  Suggestion,
  SuggestionExecuteResult,
  TradeRow,
} from "./types";

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
  runWatchlist: (executionMode: ExecutionMode = "autonomous") =>
    postJson<DecisionRow[]>(`/watchlist/run?execution_mode=${executionMode}`),
  runReplay: (maxBars = 20, executionMode: ExecutionMode = "autonomous", secondsPerTick?: number) =>
    postJson<{ status: string; max_bars: number }>(
      `/replay/run?max_bars=${maxBars}&execution_mode=${executionMode}` +
        (secondsPerTick !== undefined ? `&seconds_per_tick=${secondsPerTick}` : ""),
    ),
  squareOff: () => postJson<unknown[]>("/session/square-off"),
  startLiveSession: (executionMode: ExecutionMode = "autonomous") =>
    postJson<{ status: string }>(`/session/start?execution_mode=${executionMode}`),
  stopLiveSession: () => postJson<{ status: string }>("/session/stop"),
  sessionProgress: () => getJson<SessionProgress>("/session/progress"),
  suggestions: () => getJson<Suggestion[]>("/suggestions"),
  executeSuggestion: (symbol: string) => postJson<SuggestionExecuteResult>(`/suggestions/${symbol}/execute`),
};
