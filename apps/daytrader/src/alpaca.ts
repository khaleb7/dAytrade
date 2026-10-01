import type { Book, Order, Position } from "./types.js";

const DEFAULT_BASE = "https://paper-api.alpaca.markets";
const TARGET_EQUITY = 1000;
const DEFAULT_OFFSET = -99000;

function baseUrl(): string {
  return (process.env.APCA_API_BASE_URL || DEFAULT_BASE).replace(/\/$/, "");
}

async function alpacaRequest(method: string, apiPath: string, body?: unknown): Promise<unknown> {
  const key = process.env.APCA_API_KEY_ID || "";
  const secret = process.env.APCA_API_SECRET_KEY || "";
  if (!key || !secret) throw new Error("Missing APCA_API_KEY_ID / APCA_API_SECRET_KEY");
  const res = await fetch(`${baseUrl()}${apiPath}`, {
    method,
    headers: {
      "APCA-API-KEY-ID": key,
      "APCA-API-SECRET-KEY": secret,
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`Alpaca HTTP ${res.status} ${apiPath}: ${text}`);
  if (!text) return {};
  return JSON.parse(text) as unknown;
}

export function equityOffsetUsd(): number {
  const raw = process.env.DAYTRADE_EQUITY_OFFSET_USD;
  if (raw === undefined || raw.trim() === "") return DEFAULT_OFFSET;
  const n = Number(raw);
  return Number.isFinite(n) ? n : DEFAULT_OFFSET;
}

export function targetEquityUsd(): number {
  const raw = process.env.DAYTRADE_TARGET_EQUITY_USD;
  if (!raw) return TARGET_EQUITY;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : TARGET_EQUITY;
}

/** Map Alpaca's ~$100k paper equity onto the $1000 sizing book. */
export function sizingBook(book: Book): Book {
  if (book.sizing_view) return { ...book };
  let off = book.equity_offset_usd;
  const cash = Number(book.cash_usd || 0);
  const equity = Number(book.equity_usd || 0);
  const target = book.target_equity_usd;
  if (off !== 0 && equity + off <= 0 && equity > 0 && equity <= target * 2) off = 0;
  return {
    ...book,
    broker_cash_usd: cash,
    broker_equity_usd: equity,
    equity_offset_usd: off,
    cash_usd: cash + off,
    equity_usd: equity + off,
    buying_power: Math.max(Number(book.buying_power || 0) + off, 0),
    sizing_view: true,
  };
}

export async function reconcile(): Promise<Book> {
  const acct = (await alpacaRequest("GET", "/v2/account")) as Record<string, unknown>;
  const positionsRaw = (await alpacaRequest("GET", "/v2/positions")) as unknown;
  const rows = Array.isArray(positionsRaw) ? positionsRaw : [];
  const positions: Position[] = rows.map((p) => {
    const row = p as Record<string, unknown>;
    return {
      symbol: String(row.symbol),
      qty: Number(row.qty || 0),
      avg_cost: Number(row.avg_entry_price || 0),
      mark_price: Number(row.current_price || row.lastday_price || 0),
      market_value: Number(row.market_value || 0),
    };
  });
  return {
    broker: "alpaca_paper",
    account_id: acct.id ? String(acct.id) : undefined,
    cash_usd: Number(acct.cash || 0),
    equity_usd: Number(acct.equity || 0),
    buying_power: Number(acct.buying_power || 0),
    positions,
    status: String(acct.status || ""),
    currency: String(acct.currency || "USD"),
    target_equity_usd: targetEquityUsd(),
    equity_offset_usd: equityOffsetUsd(),
  };
}

export async function submitOrder(order: Order): Promise<Record<string, unknown>> {
  const body: Record<string, string> = {
    symbol: order.symbol.toUpperCase(),
    side: order.side,
    type: "market",
    time_in_force: "day",
  };
  if (order.side === "buy") {
    if (!(order.notional_usd > 0)) throw new Error("buy requires notional_usd > 0");
    body.notional = order.notional_usd.toFixed(2);
  } else {
    if (!(order.qty > 0)) throw new Error("sell requires qty > 0");
    body.qty = String(order.qty);
  }
  return (await alpacaRequest("POST", "/v2/orders", body)) as Record<string, unknown>;
}
