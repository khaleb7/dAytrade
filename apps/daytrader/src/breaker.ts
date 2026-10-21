import * as fs from "node:fs";
import * as path from "node:path";
import type { Order, Quote } from "./types.js";

/** A sleeve name that trades this far under its session open is sold. */
export interface BreakerMemory {
  seenSession: string | null;
  /** Prior close observed during seenSession, per symbol. */
  seenPrior: Record<string, number>;
  /** Session date the breaker tripped, per symbol. */
  tripped: Record<string, string>;
}

export function emptyBreaker(): BreakerMemory {
  return { seenSession: null, seenPrior: {}, tripped: {} };
}

export function breakerGap(): number {
  const raw = process.env.DAYTRADE_BREAKER;
  const n = raw == null || raw.trim() === "" ? 0.07 : Number(raw);
  if (!Number.isFinite(n) || n <= 0 || n >= 1) return 0;
  return n;
}

export function linePrice(open: number, gap: number): number {
  return Math.round(open * (1 - gap) * 100) / 100;
}

export function breached(quote: Quote | undefined, gap: number): boolean {
  if (!quote || !(gap > 0)) return false;
  const open = quote.session_open;
  if (open == null || !(open > 0)) return false;
  const line = linePrice(open, gap);
  if (quote.session_low != null && quote.session_low > 0 && quote.session_low <= line) return true;
  if (quote.last != null && quote.last > 0 && quote.last <= line) return true;
  return false;
}

function statePath(): string {
  const board = process.env.DAYTRADE_SCOREBOARD || "/data/scoreboard.json";
  return process.env.DAYTRADE_BREAKER_STATE || path.join(path.dirname(board), "sleeve-breaker.json");
}

export function loadBreaker(): BreakerMemory {
  const file = statePath();
  if (!fs.existsSync(file)) return emptyBreaker();
  const parsed = JSON.parse(fs.readFileSync(file, "utf8")) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("sleeve breaker state is unreadable");
  }
  const row = parsed as Partial<BreakerMemory>;
  return {
    seenSession: typeof row.seenSession === "string" ? row.seenSession : null,
    seenPrior: row.seenPrior && typeof row.seenPrior === "object" ? { ...row.seenPrior } : {},
    tripped: row.tripped && typeof row.tripped === "object" ? { ...row.tripped } : {},
  };
}

export function saveBreaker(memory: BreakerMemory): void {
  const file = statePath();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(memory, null, 2));
}

function quoteFor(quotes: Quote[], symbol: string): Quote | undefined {
  return quotes.find((quote) => quote.symbol.toUpperCase() === symbol);
}

function clone(memory: BreakerMemory): BreakerMemory {
  return {
    seenSession: memory.seenSession,
    seenPrior: { ...memory.seenPrior },
    tripped: { ...memory.tripped },
  };
}

/**
 * Sell a sleeve name through 7% under its open, and keep it unsold-back until a later session closes up.
 * The trip day itself never buys the name back.
 */
export function planBreaker(input: {
  sessionDate: string;
  slot: string;
  gap: number;
  symbols: string[];
  quotes: Quote[];
  positions: { symbol: string; qty: number }[];
  orders: Order[];
  memory: BreakerMemory;
  filledStops: Set<string>;
}): { orders: Order[]; notes: string[]; memory: BreakerMemory } {
  if (!(input.gap > 0) || input.symbols.length === 0) {
    return { orders: [...input.orders], notes: [], memory: input.memory };
  }
  const memory = clone(input.memory);
  const notes: string[] = [];
  const held = new Map<string, number>();
  for (const position of input.positions) {
    if (position.qty > 0) held.set(position.symbol.toUpperCase(), position.qty);
  }

  if (memory.seenSession && memory.seenSession < input.sessionDate) {
    for (const symbol of input.symbols) {
      const tripped = memory.tripped[symbol];
      const quote = quoteFor(input.quotes, symbol);
      const prior = quote?.prior_close;
      const seen = memory.seenPrior[symbol];
      if (!tripped || !(tripped < input.sessionDate) || !(memory.seenSession > tripped)) continue;
      if (breached(quote, input.gap)) continue;
      if (prior != null && seen != null && prior > seen) {
        delete memory.tripped[symbol];
        notes.push(`breaker clears ${symbol}`);
      }
    }
  }
  if (memory.seenSession !== input.sessionDate) {
    memory.seenSession = input.sessionDate;
    memory.seenPrior = {};
  }
  for (const symbol of input.symbols) {
    const prior = quoteFor(input.quotes, symbol)?.prior_close;
    if (prior != null && prior > 0) memory.seenPrior[symbol] = prior;
  }

  if (input.slot === "1530") {
    for (const symbol of input.symbols) {
      const tripped = memory.tripped[symbol];
      const quote = quoteFor(input.quotes, symbol);
      if (!tripped || !(tripped < input.sessionDate)) continue;
      if (breached(quote, input.gap)) continue;
      const last = quote?.last;
      const prior = quote?.prior_close;
      if (last != null && prior != null && last > prior) {
        delete memory.tripped[symbol];
        notes.push(`breaker clears ${symbol}`);
      }
    }
  }

  let orders = [...input.orders];
  for (const symbol of input.symbols) {
    const quote = quoteFor(input.quotes, symbol);
    const through = breached(quote, input.gap) || input.filledStops.has(symbol);
    if (through) memory.tripped[symbol] = input.sessionDate;
    if (!memory.tripped[symbol]) continue;
    orders = orders.filter((order) => order.symbol.toUpperCase() !== symbol);
    const qty = held.get(symbol) ?? 0;
    if (qty > 0) {
      orders.push({ side: "sell", symbol, qty });
      notes.push(`breaker sell ${symbol}`);
    } else {
      notes.push(`breaker holds ${symbol}`);
    }
  }
  return { orders, notes, memory };
}
