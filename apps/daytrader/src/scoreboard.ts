import * as fs from "node:fs";
import * as path from "node:path";
import type { Order } from "./types.js";

export interface ScorePosition {
  symbol: string;
  qty: number;
}

export interface ScoreRow {
  as_of: string;
  slot: string;
  session_date: string;
  entry_equity: number;
  cash: number;
  positions: ScorePosition[];
  marks: Record<string, number>;
  orders: Order[];
  rule_notes: string[];
  agent_decision: string;
  agent_reason: string;
  dry_run: boolean;
  excess: number | null;
}

function filePath(): string {
  return process.env.DAYTRADE_SCOREBOARD || "/data/scoreboard.json";
}

function spreadBps(): number {
  const raw = Number(process.env.DAYTRADE_SPREAD_BPS || "5");
  return Number.isFinite(raw) && raw >= 0 ? raw : 5;
}

export function minScoredSessions(): number {
  const raw = Number(process.env.DAYTRADE_MIN_SCORED_SESSIONS || "20");
  return Number.isFinite(raw) && raw >= 0 ? raw : 20;
}

function load(): ScoreRow[] {
  const file = filePath();
  if (!fs.existsSync(file)) return [];
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8")) as unknown;
    return Array.isArray(parsed) ? (parsed as ScoreRow[]) : [];
  } catch {
    return [];
  }
}

function save(rows: ScoreRow[]): void {
  const file = filePath();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(rows, null, 2));
}

function markValue(
  cash: number,
  positions: ScorePosition[],
  marks: Record<string, number>,
  fallback: Record<string, number>,
): number {
  let value = cash;
  for (const position of positions) {
    const px = marks[position.symbol] ?? fallback[position.symbol];
    if (px != null && px > 0) value += position.qty * px;
  }
  return value;
}

function applyOrders(
  cash: number,
  positions: ScorePosition[],
  orders: Order[],
  entryMarks: Record<string, number>,
  bps: number,
): { cash: number; positions: ScorePosition[] } {
  const next = positions.map((p) => ({ ...p }));
  let nextCash = cash;
  const haircut = bps / 10000;
  for (const order of orders) {
    const px = entryMarks[order.symbol];
    if (px == null || !(px > 0)) continue;
    if (order.side === "buy") {
      const notional = order.notional_usd;
      if (!(notional > 0)) continue;
      const cost = notional * (1 + haircut);
      if (cost > nextCash) continue;
      nextCash -= cost;
      const qty = notional / px;
      const held = next.find((p) => p.symbol === order.symbol);
      if (held) held.qty += qty;
      else next.push({ symbol: order.symbol, qty });
    } else {
      const held = next.find((p) => p.symbol === order.symbol);
      if (!held || !(held.qty > 0)) continue;
      const qty = Math.min(order.qty, held.qty);
      if (!(qty > 0)) continue;
      held.qty -= qty;
      nextCash += qty * px * (1 - haircut);
    }
  }
  return { cash: nextCash, positions: next.filter((p) => p.qty > 1e-8) };
}

/** One session: strategy book minus the untouched book, divided by entry equity. */
export function sessionExcess(input: {
  cash: number;
  positions: ScorePosition[];
  orders: Order[];
  entryMarks: Record<string, number>;
  nextMarks: Record<string, number>;
  bps?: number;
}): number | null {
  const entry = markValue(input.cash, input.positions, input.entryMarks, input.entryMarks);
  if (!(entry > 0)) return null;
  const hold = markValue(input.cash, input.positions, input.nextMarks, input.entryMarks);
  const applied = applyOrders(input.cash, input.positions, input.orders, input.entryMarks, input.bps ?? spreadBps());
  const strategy = markValue(applied.cash, applied.positions, input.nextMarks, input.entryMarks);
  return (strategy - hold) / entry;
}

/** Mark the latest unscored tick with prices observed now. Excess is strategy minus hold. */
export function scorePending(marksNow: Record<string, number>): number | null {
  const rows = load();
  const pending = rows.filter((row) => row.excess == null);
  const row = pending[pending.length - 1];
  if (!row || !(row.entry_equity > 0)) return null;
  const hold = markValue(row.cash, row.positions, marksNow, row.marks);
  const applied = applyOrders(row.cash, row.positions, row.orders, row.marks, spreadBps());
  const strategy = markValue(applied.cash, applied.positions, marksNow, row.marks);
  row.excess = (strategy - hold) / row.entry_equity;
  save(rows);
  return row.excess;
}

export function recordTick(row: ScoreRow): void {
  const rows = load().filter((existing) => existing.as_of !== row.as_of);
  rows.push(row);
  save(rows);
}

export function scoredSessions(): number {
  const dates = new Set<string>();
  for (const row of load()) {
    if (row.excess != null) dates.add(row.session_date);
  }
  return dates.size;
}
