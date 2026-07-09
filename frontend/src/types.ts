export type Decision = "BUY" | "SELL" | "HOLD" | "WAIT" | "SWITCH";

export interface AgentOutput {
  agent: string;
  decision: Decision;
  confidence: number;
  reasoning: string;
  evidence: string[];
  signed_vote: number;
}

export interface DebateResult {
  original_recommendations: AgentOutput[];
  contrarian_challenge: string;
  contrarian_risk_observations: string[];
  revised_recommendations: AgentOutput[];
}

export interface AlternativeCandidate {
  symbol: string;
  decision: Decision;
  confidence: number;
}

export interface DecisionRow {
  id: number;
  cycle_ts: string;
  stock: string;
  agent_recommendations: AgentOutput[];
  debate: DebateResult;
  influence_breakdown: unknown[];
  consensus_decision: Decision;
  consensus_confidence: number;
  consensus_allocation: number;
  consensus_reasoning: string;
  risk_action: "APPROVE" | "REDUCE" | "REJECT";
  risk_approved_allocation: number;
  risk_volatility_estimate: number;
  risk_reason: string;
  risk_expected_return: number;
  risk_expected_drawdown: number;
  alternatives: AlternativeCandidate[];
  action_taken: Decision;
  qty: number;
  price: number;
  cost_breakdown: Record<string, number> | null;
  net_cash_flow: number;
}

export interface TradeRow {
  id: number;
  ts: string;
  stock: string;
  action: "BUY" | "SELL";
  qty: number;
  price: number;
  cost_breakdown: Record<string, number> | null;
  net_cash_flow: number;
  decision_id: number | null;
}

export interface PortfolioSnapshotRow {
  id: number;
  ts: string;
  cash: number;
  positions: Record<string, number>;
  portfolio_value: number;
  net_pnl: number;
}

export interface PortfolioState {
  cash: number;
  positions: Record<string, number>;
}

export type ExecutionMode = "autonomous" | "manual";

/** A manual-mode committee decision awaiting an execute click -- mirrors
 * backend schemas.Suggestion, unflattened (nested consensus/risk_verdict)
 * unlike DecisionRow's flat shape. */
export interface Suggestion {
  symbol: string;
  consensus: {
    symbol: string;
    decision: Decision;
    confidence: number;
    allocation: number;
    reasoning: string;
    influence_breakdown: unknown[];
    debate: DebateResult;
    alternatives: AlternativeCandidate[];
  };
  risk_verdict: {
    action: "APPROVE" | "REDUCE" | "REJECT";
    approved_allocation: number;
    volatility_estimate: number;
    reason: string;
    expected_return: number;
    expected_drawdown: number;
  };
  revised_recommendations: AgentOutput[];
  suggested_price: number;
  suggested_at: string;
  cycle_ts: string;
}

export interface SuggestionExecuteResult {
  decision: DecisionRow;
  suggested_price: number;
  suggested_at: string;
  executing_price: number;
  executing_at: string;
}

export interface SessionProgress {
  phase: "idle" | "starting" | "discovering" | "evaluating" | "executing" | "error" | string;
  mode: "watchlist" | "replay" | null;
  detail?: string;
  universe_size?: number;
  scanned?: number;
  survived_scan?: number;
  selected_count?: number;
  watchlist?: string[];
  current_symbol?: string | null;
  symbols_completed?: number;
  symbols_total?: number;
  bars_played?: number;
  max_bars?: number;
}

export interface ReportSummary {
  base_capital: number;
  base_buying_power: number;
  current_capital: number;
  current_buying_power: number;
  portfolio_value: number;
  current_cash: number;
  trade_count: number;
  gross_pnl: number;
  total_costs: number;
  net_pnl: number;
  growth_pct: number;
  cost_breakdown_by_symbol: Record<string, { trade_count: number; total_costs: number }>;
}
