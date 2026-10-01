import type { Book, Order, Quote } from "./types.js";

export interface Target {
  symbol: string;
  weight: number;
}

export interface RuleConfig {
  targets: Target[];
  band: number;
  gapCut: number;
  cashFloor: number;
  maxName: number;
}

export interface RulePlan {
  orders: Order[];
  notes: string[];
}

const GROWTH_TARGETS = "QQQ:0.45,VTI:0.40";

export function ruleConfigFromEnv(): RuleConfig {
  const maxName = 0.45;
  const cashFloor = 0.08;
  const rawTargets = (process.env.DAYTRADE_TARGETS || "").trim();
  const single =
    process.env.DAYTRADE_CORE_SYMBOL || process.env.DAYTRADE_CORE_WEIGHT
      ? `${process.env.DAYTRADE_CORE_SYMBOL || "VTI"}:${process.env.DAYTRADE_CORE_WEIGHT || "0.25"}`
      : "";
  return {
    targets: parseTargets(rawTargets || single || GROWTH_TARGETS, maxName, 1 - cashFloor),
    band: num("DAYTRADE_REBALANCE_BAND", 0.05),
    gapCut: num("DAYTRADE_GAP_CUT", 0),
    cashFloor,
    maxName,
  };
}

function parseTargets(raw: string, maxName: number, maxSum: number): Target[] {
  const targets: Target[] = [];
  for (const part of raw.split(",")) {
    const [sym, weightRaw] = part.split(":");
    const symbol = (sym || "").trim().toUpperCase();
    const weight = Number(weightRaw);
    if (!symbol || !Number.isFinite(weight) || weight <= 0) continue;
    targets.push({ symbol, weight: Math.min(weight, maxName) });
  }
  const sum = targets.reduce((n, t) => n + t.weight, 0);
  if (sum > maxSum && sum > 0) {
    const scale = maxSum / sum;
    for (const target of targets) target.weight *= scale;
  }
  return targets;
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
    if (cfg.gapCut > 0 && quote.last <= quote.prior_close * (1 - cfg.gapCut)) gapped.add(quote.symbol);
  }
  for (const position of book.positions) {
    if (!(position.qty > 0) || !gapped.has(position.symbol)) continue;
    orders.push({ side: "sell", symbol: position.symbol, qty: position.qty });
    notes.push(`gap cut ${position.symbol}`);
  }

  const qty = new Map<string, number>();
  for (const position of book.positions) {
    if (position.qty > 0) qty.set(position.symbol, position.qty);
  }
  let cash = book.cash_usd;
  for (const order of orders) {
    if (order.side !== "sell") continue;
    const px = priceOf(order.symbol, quotes, marks);
    if (px == null) continue;
    cash += order.qty * px;
    qty.set(order.symbol, Math.max(0, (qty.get(order.symbol) ?? 0) - order.qty));
  }

  const buys: { symbol: string; notional: number }[] = [];
  for (const target of cfg.targets) {
    if (gapped.has(target.symbol)) {
      notes.push(`${target.symbol} gapped; rebalance stands aside`);
      continue;
    }
    const px = priceOf(target.symbol, quotes, marks);
    if (px == null) {
      notes.push(`no price for ${target.symbol}`);
      continue;
    }
    const heldQty = qty.get(target.symbol) ?? 0;
    const currentMv = heldQty * px;
    const weight = currentMv / equity;
    if (Math.abs(weight - target.weight) <= cfg.band) {
      notes.push(`${target.symbol} within band`);
      continue;
    }
    const targetMv = target.weight * equity;
    if (currentMv > targetMv) {
      const sellQty = Math.min((currentMv - targetMv) / px, heldQty);
      if (sellQty > 0) {
        orders.push({ side: "sell", symbol: target.symbol, qty: sellQty });
        notes.push(`rebalance sell ${target.symbol}`);
        cash += sellQty * px;
        qty.set(target.symbol, heldQty - sellQty);
      }
      continue;
    }
    buys.push({ symbol: target.symbol, notional: targetMv - currentMv });
  }

  for (const buy of buys) {
    let notional = buy.notional;
    const room = cash - cfg.cashFloor * equity;
    if (notional > room) {
      notes.push(`${buy.symbol} buy capped by cash floor`);
      notional = room;
    }
    if (notional < 1) {
      notes.push(`stand aside: cash floor (${buy.symbol})`);
      continue;
    }
    const rounded = Math.round(notional * 100) / 100;
    orders.push({ side: "buy", symbol: buy.symbol, notional_usd: rounded });
    notes.push(`rebalance buy ${buy.symbol}`);
    cash -= rounded;
  }
  if (orders.length === 0 && !notes.some((n) => n.includes("within band"))) notes.push("hold");
  return { orders, notes };
}
