export interface Position {
  symbol: string;
  qty: number;
  avg_cost: number;
  mark_price: number;
  market_value: number;
}

export interface Book {
  broker: "alpaca_paper" | "alpaca_live";
  account_id?: string;
  cash_usd: number;
  equity_usd: number;
  buying_power: number;
  positions: Position[];
  status?: string;
  currency?: string;
  target_equity_usd: number;
  equity_offset_usd: number;
  broker_cash_usd?: number;
  broker_equity_usd?: number;
  sizing_view?: boolean;
}

export type Order =
  | { side: "buy"; symbol: string; notional_usd: number }
  | { side: "sell"; symbol: string; qty: number };

export interface Proposal {
  agent_id: string;
  as_of: string;
  orders: Order[];
  thesis: string;
}

export interface Verdict {
  agent_id: string;
  as_of: string;
  decision: "accept" | "reject";
  thesis: string;
}

export interface NewsArticle {
  source: string;
  title: string;
  url: string;
  published: string;
  summary: string;
}

export interface Bar {
  symbol: string;
  ts: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
}

export interface Quote {
  symbol: string;
  session_open: number | null;
  session_high: number | null;
  session_low: number | null;
  last: number | null;
  prior_close: number | null;
  last_ts: string | null;
}

export interface TrackerContext {
  as_of: string;
  articles: NewsArticle[];
  bars: Bar[];
  quotes: Quote[];
}
