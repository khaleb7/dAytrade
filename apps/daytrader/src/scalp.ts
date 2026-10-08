import * as fs from "node:fs";
import * as path from "node:path";
import { cancelOrder, listOpenOrders, submitLimitSell, submitOrder, waitForFill } from "./alpaca.js";
import { isTradingDay } from "./calendar.js";
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
  "DIA",
  "XLF",
  "XLE",
  "GLD",
  "TSLA",
  "AVGO",
  "AMD",
  "JPM",
  "V",
  "LLY",
  "COST",
  "XOM",
  "WMT",
  "NFLX",
] as const;

const CASH_FLOOR = 0.08;
const MAX_POSITIONS = 7;
const MAX_NEW_PER_TICK = 2;
const CLIP = 0.15;
const MAX_NAME_PCT = 0.45;
const TAKE_PROFIT = 1.01;
const STOP = 0.995;
/** A name already this far above the session open has run. Leave it. */
const MAX_OPEN_GAIN = 0.004;

export interface ScalpPick {
  symbol: string;
  gain: number;
  headlined: boolean;
  /** Above the open cap, kept because the fresh trade is within 0.40% of the print from 30 minutes ago. */
  halfHour?: boolean;
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

/** 15:00 and 15:30 are the last hour. No new buys when the next day is a weekend or an NYSE holiday. */
export function scalpBuysOpen(day: Date, hour: number, minute: number): boolean {
  if (!scalpEntriesOpen(hour, minute)) return false;
  if (hour < 15) return true;
  return isTradingDay(new Date(day.getTime() + 86400000));
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

export interface ScalpSelection {
  picks: ScalpPick[];
  /** Directional qualifiers that are already more than 0.40% above the session open. */
  extended: string[];
  /** Sold already today, so not bought again. */
  reentry: string[];
}

export function selectScalpBuys(
  quotes: Quote[],
  articles: NewsArticle[],
  held: Set<string>,
  _slots: number,
  soldToday: Set<string> = new Set(),
): ScalpSelection {
  const bySymbol = new Map(quotes.map((quote) => [quote.symbol.toUpperCase(), quote]));
  const fresh: ScalpPick[] = [];
  const adding: ScalpPick[] = [];
  const extended: string[] = [];
  const reentry: string[] = [];
  for (const symbol of SCALP_WATCHLIST) {
    if (isSignalOnlySymbol(symbol)) continue;
    if (soldToday.has(symbol)) {
      reentry.push(symbol);
      continue;
    }
    const quote = bySymbol.get(symbol);
    if (!quote || quote.last == null || !(quote.last > 0)) continue;
    if (quote.session_open == null || !(quote.session_open > 0) || !(quote.last > quote.session_open)) continue;
    if (quote.prior_close == null || !(quote.prior_close > 0) || !(quote.last > quote.prior_close)) continue;
    const gain = quote.last / quote.session_open - 1;
    if (gain > MAX_OPEN_GAIN) {
      extended.push(symbol);
      continue;
    }
    const pick = { symbol, gain, headlined: mentions(symbol, articles) };
    if (held.has(symbol)) adding.push(pick);
    else fresh.push(pick);
  }
  const rank = (a: ScalpPick, b: ScalpPick) => {
    if (a.headlined !== b.headlined) return a.headlined ? -1 : 1;
    return b.gain - a.gain;
  };
  fresh.sort(rank);
  adding.sort(rank);
  return { picks: [...fresh, ...adding].sort(rank), extended, reentry };
}

/** Stored qualifiers plus names already above the open cap. The fresh check decides which ones stay. */
export function requotePicks(selection: ScalpSelection, quotes: Quote[], articles: NewsArticle[]): ScalpPick[] {
  const bySymbol = new Map(quotes.map((quote) => [quote.symbol.toUpperCase(), quote]));
  const have = new Set(selection.picks.map((pick) => pick.symbol));
  const extra: ScalpPick[] = [];
  for (const symbol of selection.extended) {
    if (have.has(symbol)) continue;
    const quote = bySymbol.get(symbol);
    const open = quote?.session_open;
    const last = quote?.last;
    const gain = open != null && open > 0 && last != null && last > 0 ? last / open - 1 : 0;
    extra.push({ symbol, gain, headlined: mentions(symbol, articles) });
  }
  return [...selection.picks, ...extra];
}

/** At most two new names. Adding to a name already held does not use that slot. */
export function limitNewNames(picks: ScalpPick[], held: Set<string>, slots: number): ScalpPick[] {
  const rank = (a: ScalpPick, b: ScalpPick) => {
    if (a.headlined !== b.headlined) return a.headlined ? -1 : 1;
    return b.gain - a.gain;
  };
  const adding = picks.filter((pick) => held.has(pick.symbol)).sort(rank);
  const fresh = picks.filter((pick) => !held.has(pick.symbol)).sort(rank);
  return [...fresh.slice(0, Math.min(Math.max(0, slots), MAX_NEW_PER_TICK)), ...adding].sort(rank);
}

/**
 * Keep a fresh trade that is above the open and the prior close when it is still within
 * 0.40% of the open, or within 0.40% of the real print from 30 minutes ago.
 */
export function applyFreshLast(
  picks: ScalpPick[],
  quotes: Quote[],
  freshLast: Record<string, number>,
  halfHour: Record<string, number> = {},
): { picks: ScalpPick[]; leftBand: string[] } {
  const bySymbol = new Map(quotes.map((quote) => [quote.symbol.toUpperCase(), quote]));
  const kept: ScalpPick[] = [];
  const leftBand: string[] = [];
  for (const pick of picks) {
    const last = freshLast[pick.symbol];
    const quote = bySymbol.get(pick.symbol);
    const open = quote?.session_open;
    const prior = quote?.prior_close;
    const gain = open != null && open > 0 && last > 0 ? last / open - 1 : Number.NaN;
    const anchor = halfHour[pick.symbol];
    const paced = anchor > 0 && last > 0 && last / anchor - 1 <= MAX_OPEN_GAIN;
    const above =
      last > 0 && open != null && open > 0 && last > open && prior != null && prior > 0 && last > prior;
    if (!above || !(gain <= MAX_OPEN_GAIN || paced)) {
      leftBand.push(pick.symbol);
      continue;
    }
    kept.push({ ...pick, gain, halfHour: !(gain <= MAX_OPEN_GAIN) && paced });
  }
  kept.sort((a, b) => {
    if (a.headlined !== b.headlined) return a.headlined ? -1 : 1;
    return b.gain - a.gain;
  });
  return { picks: kept, leftBand };
}

export function scalpSlots(positionCount: number): number {
  return Math.max(0, MAX_POSITIONS - positionCount);
}

/** Before 13:00 ET one clip stays unspent so the afternoon still has a buy. */
export function holdAfternoonClip(hour: number): boolean {
  return hour < 13;
}

/** One clip is 15% of equity. A name that still qualifies can take more clips, up to 45% of equity. */
export function scalpBuyOrders(
  picks: ScalpPick[],
  cash: number,
  equity: number,
  holdClip = false,
  heldValue: Record<string, number> = {},
): Order[] {
  if (!picks.length || !(equity > 0)) return [];
  const clip = Math.floor(equity * CLIP * 100) / 100;
  let left = cash - CASH_FLOOR * equity;
  if (holdClip) left -= clip;
  if (!(clip >= 1) || !(left >= clip)) return [];
  const added: Record<string, number> = {};
  const orders: Order[] = [];
  let progressed = true;
  while (progressed && left >= clip) {
    progressed = false;
    for (const pick of picks) {
      const have = (heldValue[pick.symbol] ?? 0) + (added[pick.symbol] ?? 0);
      if (have + clip > MAX_NAME_PCT * equity + 1e-6) continue;
      if (left < clip) break;
      orders.push({ side: "buy", symbol: pick.symbol, notional_usd: clip });
      added[pick.symbol] = (added[pick.symbol] ?? 0) + clip;
      left -= clip;
      progressed = true;
    }
  }
  return orders;
}

export interface StopPlan {
  symbol: string;
  qty: number;
}

/** A scalp the 15:55 close did not finish selling. Sold at 09:30 and 10:00. The reserved lot is not included. */
export function openExitPlans(positions: Position[], reserved: Record<string, number>): StopPlan[] {
  const plans: StopPlan[] = [];
  for (const position of positions) {
    const qty = experimentQty(position, reserved);
    if (!(qty > 1e-8)) continue;
    plans.push({ symbol: position.symbol, qty });
  }
  return plans;
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

/** Every scalp still held at 15:55 is sold. A loser is not carried into the next open. */
export function flattenPlans(positions: Position[], reserved: Record<string, number>): StopPlan[] {
  const plans: StopPlan[] = [];
  for (const position of positions) {
    const qty = experimentQty(position, reserved);
    if (!(qty > 1e-8)) continue;
    plans.push({ symbol: position.symbol, qty });
  }
  return plans;
}

export function describePicks(picks: ScalpPick[], extended: string[] = [], reentry: string[] = []): string {
  const chosen = picks.length
    ? picks
        .map(
          (pick) =>
            `${pick.symbol} ${(pick.gain * 100).toFixed(2)}%${pick.halfHour ? " half-hour" : ""}${pick.headlined ? " headline" : ""}`,
        )
        .join(", ")
    : extended.length
      ? "no name is within 0.40% of the open"
      : reentry.length
        ? "no new name is inside the entry band"
        : "no name is up versus the open and the prior close";
  const extra: string[] = [];
  if (extended.length) extra.push(`extended ${extended.join(", ")}`);
  if (reentry.length) extra.push(`reentry ${reentry.join(", ")}`);
  return extra.length ? `${chosen}; ${extra.join("; ")}` : chosen;
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

/** Cancel the resting day sell, then wait until Alpaca has released the shares. A fixed pause left the sell held_for_orders. */
async function waitUntilSellsClear(symbol: string, timeoutMs = 8000): Promise<void> {
  const upper = symbol.toUpperCase();
  const deadline = Date.now() + timeoutMs;
  while (Date.now() <= deadline) {
    const open = await listOpenOrders();
    if (!open.some((order) => order.symbol === upper && order.side === "sell")) return;
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  throw new Error(`${upper} sell still open after cancel`);
}

export async function marketSellExperiment(symbol: string, qty: number): Promise<string> {
  await cancelSells(symbol);
  await waitUntilSellsClear(symbol);
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
  const placedSell = await submitLimitSell(order.symbol, qty, limit, "day");
  return `${order.symbol} filled ${qty} @ ${px} limit ${limit} id=${String(placedSell.id || "")}`;
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
