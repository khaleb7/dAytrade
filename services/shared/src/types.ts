export type OrderSide = "buy" | "sell";

export interface HourlyOrder {
  side: OrderSide;
  symbol: string;
  notional_usd?: number;
  qty?: number;
  votes?: number;
  agents?: string[];
  scaled_to_held?: boolean;
}

export interface HourlyProposal {
  agent_id: string;
  as_of: string;
  orders: HourlyOrder[];
  thesis: string;
}

export interface ConsensusResult {
  as_of: string | null;
  orders: HourlyOrder[];
  rejected_legs: unknown[];
  no_consensus: boolean;
  proposals_loaded: string[];
  min_votes: number;
  missing_agents?: string[];
}

export interface BookPosition {
  symbol: string;
  qty: number;
  avg_cost: number;
  mark_price?: number;
  market_value?: number;
}

export interface BookPortfolio {
  broker?: string;
  cash_usd: number;
  equity_usd: number;
  buying_power?: number;
  positions: BookPosition[];
  account_id?: string;
  reconciled_at?: string | null;
  status?: string;
  currency?: string;
  target_equity_usd?: number;
  equity_offset_usd?: number;
  sizing_cash_usd?: number;
  sizing_equity_usd?: number;
  [key: string]: unknown;
}

export interface RosterAgent {
  risk_label: string;
  cash_floor_pct: number;
  max_single_name_pct: number;
  max_positions: number;
  model_id: string;
}

export interface Roster {
  agents: Record<string, RosterAgent>;
  shared_rules?: Record<string, unknown>;
  /** Fan-out spend policy (Cursor-bucket Composer only). */
  fanout_spend?: Record<string, unknown>;
}
