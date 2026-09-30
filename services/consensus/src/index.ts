import {
  activeAgentIds,
  hourlyConsensusPath,
  hourlyDir,
  readJson,
  writeJson,
  type ConsensusResult,
  type HourlyOrder,
  type HourlyProposal,
} from "@daytrade/shared";

/** Single-agent mode: roster proposal(s) become settle orders (minVotes=1). Empty = hold. */
const MIN_VOTES = 1;

function median(vals: number[]): number {
  const s = [...vals].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  if (s.length % 2 === 0) return (s[mid - 1]! + s[mid]!) / 2;
  return s[mid]!;
}

export function loadProposals(
  day: string,
  hourOrSlot: number | string,
  proposalsDir?: string,
): { loaded: HourlyProposal[]; missing: string[] } {
  const base = proposalsDir ?? hourlyDir(day, hourOrSlot);
  const loaded: HourlyProposal[] = [];
  const missing: string[] = [];
  for (const aid of activeAgentIds()) {
    const p = `${base}/${aid}.json`;
    try {
      const data = readJson<HourlyProposal>(p);
      if (!data || typeof data !== "object") {
        missing.push(aid);
        continue;
      }
      data.agent_id = data.agent_id || aid;
      loaded.push(data);
    } catch {
      missing.push(aid);
    }
  }
  return { loaded, missing };
}

export function buildConsensus(
  proposals: HourlyProposal[],
  opts: {
    asOf?: string | null;
    heldQty?: Record<string, number>;
    minVotes?: number;
  } = {},
): ConsensusResult {
  const minVotes = opts.minVotes ?? MIN_VOTES;
  const heldQty = opts.heldQty ?? {};
  const asOf =
    opts.asOf ?? proposals.find((p) => p.as_of)?.as_of ?? null;

  const buckets = new Map<string, { agent: string; size: number }[]>();
  const rejected: unknown[] = [];
  const proposalsLoaded: string[] = [];

  for (const prop of proposals) {
    const aid = prop.agent_id;
    proposalsLoaded.push(aid);
    const orders = Array.isArray(prop.orders) ? prop.orders : [];
    for (const o of orders) {
      if (!o || (o.side !== "buy" && o.side !== "sell") || typeof o.symbol !== "string") {
        rejected.push({ reason: "bad_order_shape", agent: aid, order: o });
        continue;
      }
      const symbol = o.symbol.toUpperCase();
      let size: number;
      if (o.side === "buy") {
        if (typeof o.notional_usd !== "number" || o.notional_usd <= 0) {
          rejected.push({ reason: "bad_buy_notional", agent: aid, order: o });
          continue;
        }
        size = o.notional_usd;
      } else {
        if (typeof o.qty !== "number" || o.qty <= 0) {
          rejected.push({ reason: "bad_sell_qty", agent: aid, order: o });
          continue;
        }
        size = o.qty;
      }
      const key = `${symbol}|${o.side}`;
      const list = buckets.get(key) ?? [];
      list.push({ agent: aid, size });
      buckets.set(key, list);
    }
  }

  const ordersOut: HourlyOrder[] = [];
  for (const [key, votes] of [...buckets.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    const [symbol, side] = key.split("|") as [string, "buy" | "sell"];
    const agents = votes.map((v) => v.agent);
    const sizes = votes.map((v) => v.size);
    if (votes.length < minVotes) {
      rejected.push({
        symbol,
        side,
        votes: votes.length,
        agents,
        reason: "below_majority",
      });
      continue;
    }
    let med = median(sizes);
    if (side === "buy") {
      med = Math.round(med * 100) / 100;
      ordersOut.push({
        side: "buy",
        symbol,
        notional_usd: med,
        votes: votes.length,
        agents,
      });
    } else {
      const held = heldQty[symbol] ?? 0;
      let qty = Math.round(med * 1e6) / 1e6;
      const scaled = held > 0 && qty > held;
      if (scaled) qty = Math.round(held * 1e6) / 1e6;
      ordersOut.push({
        side: "sell",
        symbol,
        qty,
        votes: votes.length,
        agents,
        scaled_to_held: scaled,
      });
    }
  }

  return {
    as_of: asOf,
    orders: ordersOut,
    rejected_legs: rejected,
    no_consensus: ordersOut.length === 0,
    proposals_loaded: proposalsLoaded.filter(Boolean),
    min_votes: minVotes,
  };
}

export function writeConsensus(
  day: string,
  hourOrSlot: number | string,
  consensus: ConsensusResult,
): string {
  const out = hourlyConsensusPath(day, hourOrSlot);
  writeJson(out, consensus);
  return out;
}

export { hourlyDir };
