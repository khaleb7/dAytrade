import {
  alpacaConfigPath,
  bookPortfolioPath,
  isoZ,
  readJson,
  writeJson,
  type BookPortfolio,
  type BookPosition,
  type ConsensusResult,
  type HourlyOrder,
} from "@daytrade/shared";

const DEFAULT_BASE = "https://paper-api.alpaca.markets";
const TARGET_EQUITY = 1000;
const DEFAULT_OFFSET = -99000;
const CASH_FLOOR_PCT = 15;
const MAX_SINGLE_NAME_PCT = 35;
const MAX_POSITIONS = 6;
const TICKER_RE = /^[A-Z][A-Z0-9.\-]{0,9}$/;

export interface AlpacaConfig {
  paper?: boolean;
  base_url?: string;
  target_equity_usd?: number;
  equity_offset_usd?: number;
  note?: string;
}

export function loadAlpacaConfig(): AlpacaConfig {
  try {
    return readJson<AlpacaConfig>(alpacaConfigPath());
  } catch {
    return {
      paper: true,
      base_url: DEFAULT_BASE,
      target_equity_usd: TARGET_EQUITY,
      equity_offset_usd: DEFAULT_OFFSET,
    };
  }
}

export function equityOffsetUsd(cfg?: AlpacaConfig): number {
  const c = cfg ?? loadAlpacaConfig();
  const raw = c.equity_offset_usd ?? DEFAULT_OFFSET;
  const n = Number(raw);
  return Number.isFinite(n) ? n : DEFAULT_OFFSET;
}

export function sizingBook(
  book: BookPortfolio,
  opts: { offset?: number; cfg?: AlpacaConfig } = {},
): BookPortfolio {
  if (book.sizing_view) return { ...book };
  const cfg = opts.cfg ?? loadAlpacaConfig();
  let off = opts.offset !== undefined ? opts.offset : equityOffsetUsd(cfg);
  const cash = Number(book.cash_usd || 0);
  let equity = Number(book.equity_usd || 0);
  if (!book.equity_usd && book.positions?.length) {
    const mv = book.positions.reduce(
      (s, p) =>
        s +
        Number(
          p.market_value ??
            Number(p.qty || 0) * Number(p.mark_price ?? p.avg_cost ?? 0),
        ),
      0,
    );
    equity = cash + mv;
  }
  const target = Number(cfg.target_equity_usd ?? TARGET_EQUITY);
  if (off !== 0 && equity + off <= 0 && equity > 0 && equity <= target * 2) {
    off = 0;
  }
  const view: BookPortfolio = {
    ...book,
    broker_cash_usd: cash,
    broker_equity_usd: equity,
    equity_offset_usd: off,
    cash_usd: cash + off,
    equity_usd: equity + off,
    sizing_view: true,
    target_equity_usd: target,
  };
  if (book.buying_power != null) {
    const bp = Number(book.buying_power);
    view.buying_power = Math.max(bp + off, 0);
  }
  return view;
}

export function credentialsPresent(): boolean {
  return Boolean(process.env.APCA_API_KEY_ID && process.env.APCA_API_SECRET_KEY);
}

async function alpacaRequest(
  method: string,
  apiPath: string,
  body?: unknown,
): Promise<unknown> {
  const key = process.env.APCA_API_KEY_ID || "";
  const secret = process.env.APCA_API_SECRET_KEY || "";
  if (!key || !secret) throw new Error("Missing APCA_API_KEY_ID / APCA_API_SECRET_KEY");
  const cfg = loadAlpacaConfig();
  const base = (process.env.APCA_API_BASE_URL || cfg.base_url || DEFAULT_BASE).replace(
    /\/$/,
    "",
  );
  const res = await fetch(`${base}${apiPath}`, {
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
  return JSON.parse(text);
}

export async function getAccount(): Promise<Record<string, unknown>> {
  return (await alpacaRequest("GET", "/v2/account")) as Record<string, unknown>;
}

export async function listPositions(): Promise<Record<string, unknown>[]> {
  const data = await alpacaRequest("GET", "/v2/positions");
  return Array.isArray(data) ? data : [];
}

export async function reconcile(outPath = bookPortfolioPath()): Promise<BookPortfolio> {
  const acct = await getAccount();
  const positionsRaw = await listPositions();
  const cash = Number(acct.cash || 0);
  const equity = Number(acct.equity || 0);
  const positions: BookPosition[] = positionsRaw.map((p) => ({
    symbol: String(p.symbol),
    qty: Number(p.qty || 0),
    avg_cost: Number(p.avg_entry_price || 0),
    mark_price: Number(p.current_price || p.lastday_price || 0),
    market_value: Number(p.market_value || 0),
  }));
  const cfg = loadAlpacaConfig();
  const mirror: BookPortfolio = {
    broker: "alpaca_paper",
    account_id: acct.id as string,
    cash_usd: cash,
    equity_usd: equity,
    buying_power: Number(acct.buying_power || 0),
    positions,
    reconciled_at: isoZ(),
    status: String(acct.status || ""),
    currency: String(acct.currency || "USD"),
    target_equity_usd: cfg.target_equity_usd ?? TARGET_EQUITY,
    equity_offset_usd: equityOffsetUsd(cfg),
  };
  const sized = sizingBook(mirror, { cfg });
  mirror.sizing_cash_usd = sized.cash_usd;
  mirror.sizing_equity_usd = sized.equity_usd;
  writeJson(outPath, mirror);
  return mirror;
}

export async function submitMarketOrder(opts: {
  symbol: string;
  side: "buy" | "sell";
  notional?: number;
  qty?: number;
}): Promise<Record<string, unknown>> {
  const body: Record<string, string> = {
    symbol: opts.symbol.toUpperCase(),
    side: opts.side,
    type: "market",
    time_in_force: "day",
  };
  if (opts.side === "buy") {
    if (!opts.notional || opts.notional <= 0) throw new Error("buy requires notional > 0");
    body.notional = opts.notional.toFixed(2);
  } else {
    if (!opts.qty || opts.qty <= 0) throw new Error("sell requires qty > 0");
    body.qty = String(opts.qty);
  }
  return (await alpacaRequest("POST", "/v2/orders", body)) as Record<string, unknown>;
}

export function submitConsensusOrders(
  orders: HourlyOrder[],
  opts: { dryRun?: boolean } = {},
): Promise<{ order: HourlyOrder; dry_run: boolean; status: string; error?: string; alpaca?: unknown }[]> {
  const dryRun = opts.dryRun !== false;
  return Promise.all(
    orders.map(async (o) => {
      if (dryRun) return { order: o, dry_run: true, status: "dry_run_skip" };
      try {
        const resp =
          o.side === "buy"
            ? await submitMarketOrder({
                symbol: o.symbol,
                side: "buy",
                notional: Number(o.notional_usd),
              })
            : await submitMarketOrder({
                symbol: o.symbol,
                side: "sell",
                qty: Number(o.qty),
              });
        return {
          order: o,
          dry_run: false,
          status: "submitted",
          alpaca: { id: resp.id, status: resp.status, symbol: resp.symbol },
        };
      } catch (e) {
        return {
          order: o,
          dry_run: false,
          status: "error",
          error: e instanceof Error ? e.message : String(e),
        };
      }
    }),
  );
}

function simulateFills(
  portfolio: { cash_usd: number; positions: BookPosition[] },
  orders: HourlyOrder[],
  prices: Record<string, number>,
): { ok: true; snap: { cash_usd: number; positions: BookPosition[]; equity_usd: number } } | { ok: false; errors: string[] } {
  const errors: string[] = [];
  let cash = Number(portfolio.cash_usd);
  const pos = new Map<string, BookPosition>();
  for (const p of portfolio.positions || []) pos.set(p.symbol, { ...p });

  for (let i = 0; i < orders.length; i++) {
    const o = orders[i]!;
    const symbol = o.symbol.toUpperCase();
    if (!TICKER_RE.test(symbol)) {
      errors.push(`orders[${i}]: invalid symbol`);
      continue;
    }
    const px = prices[symbol];
    if (px == null || px <= 0) {
      errors.push(`orders[${i}]: no mark/price for ${symbol}`);
      continue;
    }
    if (o.side === "buy") {
      const notional = Number(o.notional_usd);
      if (!(notional > 0)) {
        errors.push(`orders[${i}]: notional_usd must be > 0`);
        continue;
      }
      if (notional > cash + 1e-9) {
        errors.push(`orders[${i}]: insufficient cash`);
        continue;
      }
      const qty = notional / px;
      cash -= notional;
      const cur = pos.get(symbol);
      if (cur) {
        const newQty = Number(cur.qty) + qty;
        const newCost = Number(cur.avg_cost) * Number(cur.qty) + notional;
        pos.set(symbol, {
          symbol,
          qty: newQty,
          avg_cost: newCost / newQty,
          mark_price: px,
        });
      } else {
        pos.set(symbol, { symbol, qty, avg_cost: px, mark_price: px });
      }
    } else {
      const qty = Number(o.qty);
      if (!(qty > 0)) {
        errors.push(`orders[${i}]: qty must be > 0`);
        continue;
      }
      const cur = pos.get(symbol);
      if (!cur) {
        errors.push(`orders[${i}]: cannot sell unheld ${symbol}`);
        continue;
      }
      if (qty > Number(cur.qty) + 1e-9) {
        errors.push(`orders[${i}]: sell qty > held`);
        continue;
      }
      cash += qty * px;
      const rem = Number(cur.qty) - qty;
      if (rem <= 1e-12) pos.delete(symbol);
      else
        pos.set(symbol, {
          symbol,
          qty: rem,
          avg_cost: cur.avg_cost,
          mark_price: px,
        });
    }
  }
  if (errors.length) return { ok: false, errors };
  const positions = [...pos.values()];
  let equity = cash;
  for (const p of positions) {
    const px = prices[p.symbol] ?? p.mark_price ?? p.avg_cost;
    equity += Number(p.qty) * Number(px);
  }
  return { ok: true, snap: { cash_usd: cash, positions, equity_usd: equity } };
}

export function validateBook(
  consensus: ConsensusResult,
  book: BookPortfolio,
  prices?: Record<string, number> | null,
  opts: { applySizingOffset?: boolean } = {},
): {
  ok: boolean;
  errors: string[];
  post_trade: unknown;
  hold?: boolean;
  sizing_view?: boolean;
  equity_offset_usd?: number;
} {
  const apply = opts.applySizingOffset !== false;
  const work = apply ? sizingBook(book) : book;
  const orders = consensus.orders || [];
  if (!orders.length) {
    return {
      ok: true,
      errors: [],
      post_trade: {
        cash_usd: work.cash_usd,
        positions: work.positions,
        equity_usd: work.equity_usd,
      },
      hold: true,
      sizing_view: Boolean(work.sizing_view),
      equity_offset_usd: work.equity_offset_usd as number | undefined,
    };
  }

  const px: Record<string, number> = { ...(prices || {}) };
  for (const p of work.positions || []) {
    if (p.mark_price || p.avg_cost) px[p.symbol] = Number(p.mark_price ?? p.avg_cost);
  }

  const clean: HourlyOrder[] = orders.map((o) =>
    o.side === "buy"
      ? { side: "buy", symbol: o.symbol.toUpperCase(), notional_usd: o.notional_usd }
      : { side: "sell", symbol: o.symbol.toUpperCase(), qty: o.qty },
  );

  const sim = simulateFills(
    { cash_usd: Number(work.cash_usd), positions: work.positions || [] },
    clean,
    px,
  );
  if (!sim.ok) return { ok: false, errors: sim.errors, post_trade: null };

  const errors: string[] = [];
  const { cash_usd: cash, positions, equity_usd: equity } = sim.snap;
  if (equity <= 0) errors.push("post-trade equity must be positive");
  if (cash + 1e-9 < (CASH_FLOOR_PCT / 100) * equity) {
    errors.push(
      `cash floor breached: cash=${cash} < ${CASH_FLOOR_PCT}% of equity=${equity}`,
    );
  }
  for (const p of positions) {
    const price = px[p.symbol] ?? p.mark_price ?? p.avg_cost;
    const mv = Number(p.qty) * Number(price);
    if (mv > (MAX_SINGLE_NAME_PCT / 100) * equity + 1e-6) {
      errors.push(
        `max single name breached: ${p.symbol} mv=${mv} > ${MAX_SINGLE_NAME_PCT}% of equity`,
      );
    }
  }
  if (positions.length > MAX_POSITIONS) {
    errors.push(`max positions breached: ${positions.length} > ${MAX_POSITIONS}`);
  }
  if (errors.length) {
    return {
      ok: false,
      errors,
      post_trade: null,
      equity_offset_usd: work.equity_offset_usd as number | undefined,
    };
  }
  return {
    ok: true,
    errors: [],
    post_trade: sim.snap,
    sizing_view: Boolean(work.sizing_view),
    equity_offset_usd: work.equity_offset_usd as number | undefined,
    broker_cash_usd: work.broker_cash_usd,
    broker_equity_usd: work.broker_equity_usd,
  } as ReturnType<typeof validateBook> & {
    broker_cash_usd?: unknown;
    broker_equity_usd?: unknown;
  };
}
