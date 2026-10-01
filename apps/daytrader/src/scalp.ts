import * as fs from "node:fs";
import * as path from "node:path";
import { cancelOrder, listOpenOrders, submitLimitSell, submitOrder, waitForFill } from "./alpaca.js";
import type { NewsArticle, Order, Position, Quote } from "./types.js";
import { isSignalOnlySymbol } from "./validate.js";

/** Names Newstracker already prices, minus the reserved sleeve lot (VTI). */
export const SCALP_WATCHLIST = [
  "SPY",
  "QQQ",
  "IWM",
  "TLT",
  "USO",
  "AAPL",
  "MSFT",
  "NVDA",
  "AMZN",
  "GOOGL",
  "META",
] as const;

const CASH_FLOOR = 0.08;
const MAX_POSITIONS = 7;
const MAX_NEW_PER_TICK = 2;
const CLIP = 0.15;
const TAKE_PROFIT = 1.01;
const STOP = 0.995;

export interface ScalpPick {
  symbol: string;
  gain: number;
  headlined: boolean;
}

/** Scalp is the daytrade. The QQQ/VTI sleeve runs only when DAYTRADE_MODE is not scalp. */
export function scalpActive(_session?: string): boolean {
  return (process.env.DAYTRADE_MODE || "").trim().toLowerCase() === "scalp";
}

/** 09:30 and 10:00 are the opening rush. New buys start at 10:30. */
export function scalpEntriesOpen(hour: number, minute: number): boolean {
  if (hour > 10) return true;
  return hour === 10 && minute >= 30;
}

export function armScalpScoreboard(): void {
  process.env.DAYTRADE_SCOREBOARD = process.env.DAYTRADE_SCALP_SCOREBOARD || "/data/scoreboard-scalp.json";
}

function reservePath(): string {
  return process.env.DAYTRADE_SCALP_RESERVE || "/data/scalp-reserve.json";
}

/** First call snapshots every share already on the book. Later calls never rewrite it. */
export function loadReserve(positions: Position[]): Record<string, number> {
  const file = reservePath();
  if (fs.existsSync(file)) {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8")) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("scalp reserve is unreadable");
    }
    const reserved: Record<string, number> = {};
    for (const [symbol, qty] of Object.entries(parsed as Record<string, unknown>)) {
      const n = Number(qty);
      if (Number.isFinite(n) && n > 0) reserved[symbol.toUpperCase()] = n;
    }
    return reserved;
  }
  const reserved: Record<string, number> = {};
  for (const position of positions) {
    if (position.qty > 0) reserved[position.symbol.toUpperCase()] = position.qty;
  }
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(reserved, null, 2));
  console.log(`[daytrader] scalp reserve ${JSON.stringify(reserved)}`);
  return reserved;
}

export function experimentQty(position: Position, reserved: Record<string, number>): number {
  return Math.max(0, position.qty - (reserved[position.symbol.toUpperCase()] ?? 0));
}

export function limitPrice(entry: number): number {
  return Math.round(entry * TAKE_PROFIT * 100) / 100;
}

function mentions(symbol: string, articles: NewsArticle[]): boolean {
  const re = new RegExp(`\\b${symbol}\\b`, "i");
  return articles.some((article) => re.test(`${article.title} ${article.summary}`));
}

export function selectScalpBuys(
  quotes: Quote[],
  articles: NewsArticle[],
  held: Set<string>,
  slots: number,
): ScalpPick[] {
  if (slots <= 0) return [];
  const bySymbol = new Map(quotes.map((quote) => [quote.symbol.toUpperCase(), quote]));
  const picks: ScalpPick[] = [];
  for (const symbol of SCALP_WATCHLIST) {
    if (held.has(symbol) || isSignalOnlySymbol(symbol)) continue;
    const quote = bySymbol.get(symbol);
    if (!quote || quote.last == null || !(quote.last > 0)) continue;
    if (quote.session_open == null || !(quote.session_open > 0) || !(quote.last > quote.session_open)) continue;
    if (quote.prior_close == null || !(quote.prior_close > 0) || !(quote.last > quote.prior_close)) continue;
    picks.push({
      symbol,
      gain: quote.last / quote.session_open - 1,
      headlined: mentions(symbol, articles),
    });
  }
  picks.sort((a, b) => {
    if (a.headlined !== b.headlined) return a.headlined ? -1 : 1;
    return b.gain - a.gain;
  });
  return picks.slice(0, Math.min(slots, MAX_NEW_PER_TICK));
}

export function scalpSlots(positionCount: number): number {
  return Math.max(0, MAX_POSITIONS - positionCount);
}

/** Fixed clip, 15% of equity, and only as many as the cash floor allows. The rest of the cash stays for later ticks. */
export function scalpNotionals(cash: number, equity: number, count: number): number[] {
  if (count <= 0 || !(equity > 0)) return [];
  const clip = Math.floor(equity * CLIP * 100) / 100;
  let left = cash - CASH_FLOOR * equity;
  if (!(clip >= 1) || !(left >= clip)) return [];
  const notionals: number[] = [];
  for (let i = 0; i < count && left >= clip; i++) {
    notionals.push(clip);
    left -= clip;
  }
  return notionals;
}

export function scalpBuyOrders(picks: ScalpPick[], cash: number, equity: number): Order[] {
  const notionals = scalpNotionals(cash, equity, picks.length);
  const orders: Order[] = [];
  for (let i = 0; i < notionals.length; i++) {
    orders.push({ side: "buy", symbol: picks[i].symbol, notional_usd: notionals[i] });
  }
  return orders;
}

export interface StopPlan {
  symbol: string;
  qty: number;
}

/** A scalp down 0.5% from its average cost is closed so that cash can take a later setup. */
export function stopPlans(
  positions: Position[],
  reserved: Record<string, number>,
  marks: Record<string, number>,
): StopPlan[] {
  const plans: StopPlan[] = [];
  for (const position of positions) {
    const qty = experimentQty(position, reserved);
    if (!(qty > 1e-8) || !(position.avg_cost > 0)) continue;
    const mark = marks[position.symbol] ?? position.mark_price;
    if (!(mark > 0) || mark > position.avg_cost * STOP) continue;
    plans.push({ symbol: position.symbol, qty });
  }
  return plans;
}

export interface FlattenPlan {
  symbol: string;
  qty: number;
  limit: number;
  /** Mark is at or above average cost, so the close sells it. */
  marketSell: boolean;
}

export function flattenPlans(
  positions: Position[],
  reserved: Record<string, number>,
  marks: Record<string, number>,
): FlattenPlan[] {
  const plans: FlattenPlan[] = [];
  for (const position of positions) {
    const qty = experimentQty(position, reserved);
    if (!(qty > 1e-8)) continue;
    const mark = marks[position.symbol] ?? position.mark_price;
    if (!(mark > 0) || !(position.avg_cost > 0)) continue;
    plans.push({
      symbol: position.symbol,
      qty,
      limit: limitPrice(position.avg_cost),
      marketSell: mark + 1e-9 >= position.avg_cost,
    });
  }
  return plans;
}

export function describePicks(picks: ScalpPick[]): string {
  if (!picks.length) return "no name is up versus the open and the prior close";
  return picks
    .map((pick) => `${pick.symbol} ${(pick.gain * 100).toFixed(2)}%${pick.headlined ? " headline" : ""}`)
    .join(", ");
}

async function cancelSells(symbol: string): Promise<void> {
  const open = await listOpenOrders();
  for (const order of open) {
    if (order.symbol === symbol.toUpperCase() && order.side === "sell") await cancelOrder(order.id);
  }
}

export async function restLimit(
  symbol: string,
  qty: number,
  limit: number,
  timeInForce: "day" | "gtc",
): Promise<string> {
  await cancelSells(symbol);
  const placed = await submitLimitSell(symbol, qty, limit, timeInForce);
  return String(placed.id || "");
}

export async function marketSellExperiment(symbol: string, qty: number): Promise<string> {
  await cancelSells(symbol);
  await new Promise((resolve) => setTimeout(resolve, 300));
  const placed = await submitOrder({ side: "sell", symbol, qty });
  return String(placed.id || "");
}

export async function buyThenLimit(order: Order): Promise<string> {
  if (order.side !== "buy") throw new Error("scalp entry is a buy");
  const placed = await submitOrder(order);
  const id = String(placed.id || "");
  const filled = await waitForFill(id);
  const px = filled.filledAvgPrice;
  const qty = filled.filledQty;
  if (!(px > 0) || !(qty > 0)) throw new Error(`${order.symbol} fill missing price or qty`);
  const limit = limitPrice(px);
  const sellId = await restLimit(order.symbol, qty, limit, "day");
  return `${order.symbol} filled ${qty} @ ${px} limit ${limit} id=${sellId}`;
}

/** Day limit for an experiment lot that has no working sell. Covers an expired day order or a rejected GTC. */
export async function rearmUncovered(positions: Position[], reserved: Record<string, number>): Promise<string[]> {
  const open = await listOpenOrders();
  const covered = new Set(open.filter((order) => order.side === "sell").map((order) => order.symbol));
  const notes: string[] = [];
  for (const position of positions) {
    const qty = experimentQty(position, reserved);
    const symbol = position.symbol.toUpperCase();
    if (!(qty > 1e-8) || covered.has(symbol) || !(position.avg_cost > 0)) continue;
    const limit = limitPrice(position.avg_cost);
    const id = await restLimit(symbol, qty, limit, "day");
    notes.push(`${symbol} rearmed day limit ${limit} id=${id}`);
  }
  return notes;
}
