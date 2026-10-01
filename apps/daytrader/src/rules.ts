import type { Book, Order, Quote } from "./types.js";

export interface RuleConfig {
  coreSymbol: string;
  coreWeight: number;
  band: number;
  gapCut: number;
  cashFloor: number;
}

export interface RulePlan {
  orders: Order[];
  notes: string[];
}

export function ruleConfigFromEnv(): RuleConfig {
  return {
    coreSymbol: (process.env.DAYTRADE_CORE_SYMBOL || "VTI").trim().toUpperCase() || "VTI",
    coreWeight: num("DAYTRADE_CORE_WEIGHT", 0.25),
    band: num("DAYTRADE_REBALANCE_BAND", 0.05),
    gapCut: num("DAYTRADE_GAP_CUT", 0.03),
    cashFloor: 0.08,
  };
}

function num(name: string, fallback: number): number {
  const raw = Number(process.env[name]);
  return Number.isFinite(raw) && raw >= 0 ? raw : fallback;
}

function priceOf(symbol: string, quotes: Quote[], marks: Record<string, number>): number | null {
  const quote = quotes.find((q) => q.symbol === symbol);
  if (quote?.last != null && quote.last > 0) return quote.last;
  const mark = marks[symbol];
  return mark != null && mark > 0 ? mark : null;
}

/** Pre-declared orders. The agent may veto the batch. It does not add names. */
export function buildRuleOrders(book: Book, quotes: Quote[], cfg: RuleConfig): RulePlan {
  const notes: string[] = [];
  const orders: Order[] = [];
  const equity = book.equity_usd;
  if (!(equity > 0)) {
    notes.push("no equity");
    return { orders, notes };
  }
  const marks: Record<string, number> = {};
  for (const p of book.positions) {
    if (p.mark_price > 0) marks[p.symbol] = p.mark_price;
  }
  const gapped = new Set<string>();
  for (const quote of quotes) {
    if (quote.prior_close == null || quote.last == null || !(quote.prior_close > 0)) continue;
    if (quote.last <= quote.prior_close * (1 - cfg.gapCut)) gapped.add(quote.symbol);
  }
  for (const position of book.positions) {
    if (!(position.qty > 0) || !gapped.has(position.symbol)) continue;
    orders.push({ side: "sell", symbol: position.symbol, qty: position.qty });
    notes.push(`gap cut ${position.symbol}`);
  }

  if (gapped.has(cfg.coreSymbol)) {
    notes.push(`core ${cfg.coreSymbol} gapped; rebalance stands aside`);
    if (orders.length === 0) notes.push("hold");
    return { orders, notes };
  }

  const px = priceOf(cfg.coreSymbol, quotes, marks);
  if (px == null) {
    notes.push(`no price for ${cfg.coreSymbol}`);
    return { orders, notes };
  }
  const held = book.positions.find((p) => p.symbol === cfg.coreSymbol);
  const currentMv = held && held.qty > 0 ? held.qty * px : 0;
  const weight = currentMv / equity;
  if (Math.abs(weight - cfg.coreWeight) <= cfg.band) {
    notes.push(`core ${cfg.coreSymbol} within band`);
    return { orders, notes };
  }
  const targetMv = cfg.coreWeight * equity;
  if (currentMv > targetMv) {
    const qty = (currentMv - targetMv) / px;
    const sellQty = Math.min(qty, held?.qty ?? 0);
    if (sellQty > 0) {
      orders.push({ side: "sell", symbol: cfg.coreSymbol, qty: sellQty });
      notes.push(`rebalance sell ${cfg.coreSymbol}`);
    }
    return { orders, notes };
  }
  let buy = targetMv - currentMv;
  const room = book.cash_usd - cfg.cashFloor * equity;
  if (buy > room) {
    notes.push("buy capped by cash floor");
    buy = room;
  }
  if (buy < 1) {
    notes.push("stand aside: cash floor");
    return { orders, notes };
  }
  orders.push({ side: "buy", symbol: cfg.coreSymbol, notional_usd: Math.round(buy * 100) / 100 });
  notes.push(`rebalance buy ${cfg.coreSymbol}`);
  return { orders, notes };
}
