import type { Book, Order, Position } from "./types.js";

const CASH_FLOOR_PCT = 8;
const MAX_SINGLE_NAME_PCT = 45;
const MAX_POSITIONS = 7;
const TICKER_RE = /^[A-Z][A-Z0-9.\-]{0,9}$/;
const SIGNAL_ONLY = new Set([
  "VIX",
  "VXX",
  "UVXY",
  "UVIX",
  "SVIX",
  "SVXY",
  "VIXY",
  "VIXM",
  "VXZ",
  "TVIX",
]);

export function isSignalOnlySymbol(symbol: string): boolean {
  const up = symbol.toUpperCase().trim();
  if (SIGNAL_ONLY.has(up)) return true;
  if (up.includes("=") || up.startsWith("^")) return true;
  return false;
}

function simulate(
  cash0: number,
  positions0: Position[],
  orders: Order[],
  prices: Record<string, number>,
): { ok: true; cash: number; positions: Position[]; equity: number } | { ok: false; errors: string[] } {
  const errors: string[] = [];
  let cash = cash0;
  const pos = new Map<string, Position>();
  for (const p of positions0) pos.set(p.symbol, { ...p });

  orders.forEach((o, i) => {
    const symbol = o.symbol.toUpperCase();
    if (!TICKER_RE.test(symbol)) {
      errors.push(`orders[${i}]: invalid symbol`);
      return;
    }
    if (isSignalOnlySymbol(symbol)) {
      errors.push(`orders[${i}]: ${symbol} is signal-only`);
      return;
    }
    const px = prices[symbol];
    if (px == null || px <= 0) {
      errors.push(`orders[${i}]: no mark/price for ${symbol}`);
      return;
    }
    if (o.side === "buy") {
      const notional = o.notional_usd;
      if (!(notional > 0)) {
        errors.push(`orders[${i}]: notional_usd must be > 0`);
        return;
      }
      if (notional > cash + 1e-9) {
        errors.push(`orders[${i}]: insufficient cash`);
        return;
      }
      const qty = notional / px;
      cash -= notional;
      const cur = pos.get(symbol);
      if (cur) {
        const newQty = cur.qty + qty;
        const newCost = cur.avg_cost * cur.qty + notional;
        pos.set(symbol, { symbol, qty: newQty, avg_cost: newCost / newQty, mark_price: px, market_value: newQty * px });
      } else {
        pos.set(symbol, { symbol, qty, avg_cost: px, mark_price: px, market_value: notional });
      }
    } else {
      const qty = o.qty;
      if (!(qty > 0)) {
        errors.push(`orders[${i}]: qty must be > 0`);
        return;
      }
      const cur = pos.get(symbol);
      if (!cur) {
        errors.push(`orders[${i}]: cannot sell unheld ${symbol}`);
        return;
      }
      if (qty > cur.qty + 1e-9) {
        errors.push(`orders[${i}]: sell qty > held`);
        return;
      }
      cash += qty * px;
      const rem = cur.qty - qty;
      if (rem <= 1e-12) pos.delete(symbol);
      else pos.set(symbol, { ...cur, qty: rem, mark_price: px, market_value: rem * px });
    }
  });
  if (errors.length) return { ok: false, errors };
  const positions = [...pos.values()];
  let equity = cash;
  for (const p of positions) equity += p.qty * (prices[p.symbol] ?? p.mark_price ?? p.avg_cost);
  return { ok: true, cash, positions, equity };
}

export function validateOrders(
  orders: Order[],
  book: Book,
  prices: Record<string, number>,
): { ok: boolean; errors: string[]; hold: boolean } {
  if (!orders.length) return { ok: true, errors: [], hold: true };
  const px = { ...prices };
  for (const p of book.positions) {
    if (p.mark_price || p.avg_cost) px[p.symbol] = Number(p.mark_price || p.avg_cost);
  }
  const sim = simulate(book.cash_usd, book.positions, orders, px);
  if (!sim.ok) return { ok: false, errors: sim.errors, hold: false };
  const errors: string[] = [];
  if (sim.equity <= 0) errors.push("post-trade equity must be positive");
  if (sim.cash + 1e-9 < (CASH_FLOOR_PCT / 100) * sim.equity) {
    errors.push(`cash floor breached: cash=${sim.cash} < ${CASH_FLOOR_PCT}% of equity=${sim.equity}`);
  }
  for (const p of sim.positions) {
    const price = px[p.symbol] ?? p.mark_price ?? p.avg_cost;
    const mv = p.qty * price;
    if (mv > (MAX_SINGLE_NAME_PCT / 100) * sim.equity + 1e-6) {
      errors.push(`max single name breached: ${p.symbol} mv=${mv} > ${MAX_SINGLE_NAME_PCT}% of equity`);
    }
  }
  if (sim.positions.length > MAX_POSITIONS) {
    errors.push(`max positions breached: ${sim.positions.length} > ${MAX_POSITIONS}`);
  }
  if (errors.length) return { ok: false, errors, hold: false };
  return { ok: true, errors: [], hold: false };
}
