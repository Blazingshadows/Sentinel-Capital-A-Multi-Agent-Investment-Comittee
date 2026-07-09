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
