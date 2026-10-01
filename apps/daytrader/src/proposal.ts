import * as fs from "node:fs";
import * as path from "node:path";
import type { Order, Proposal } from "./types.js";

export type StreamCapture = {
  text: string;
  writes: { path: string; fileText: string }[];
};

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : null;
}

export function absorbStreamEvent(ev: unknown, cap: StreamCapture): void {
  const o = asRecord(ev);
  if (!o) return;
  if (o.type === "text-delta" && typeof o.text === "string") cap.text += o.text;
  if (typeof o.text === "string" && o.type !== "text-delta") cap.text += o.text;
  const message = asRecord(o.message);
  const content = message?.content;
  if (Array.isArray(content)) {
    for (const block of content) {
      const b = asRecord(block);
      if (b?.type === "text" && typeof b.text === "string") cap.text += b.text;
    }
  }
  const tc = asRecord(o.toolCall) || asRecord(o.tool_call);
  const type = tc?.type;
  if (type === "write" || type === "Write") {
    const args = asRecord(tc?.args) || tc;
    const p = args?.path;
    const fileText = args?.fileText || args?.contents || args?.content;
    if (typeof p === "string" && typeof fileText === "string") {
      cap.writes.push({ path: p, fileText });
    }
  }
}

function looksLikeProposal(obj: unknown): obj is Record<string, unknown> {
  const o = asRecord(obj);
  if (!o) return false;
  return typeof o.agent_id === "string" && Array.isArray(o.orders) && typeof o.thesis === "string";
}

export function extractProposalJson(text: string): Record<string, unknown> | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const fenceRe = /```(?:json)?\s*([\s\S]*?)```/gi;
  let m: RegExpExecArray | null;
  while ((m = fenceRe.exec(trimmed))) {
    try {
      const parsed = JSON.parse(m[1]!.trim()) as unknown;
      if (looksLikeProposal(parsed)) return parsed;
    } catch {
      /* next fence */
    }
  }
  const starts: number[] = [];
  for (let i = 0; i < trimmed.length; i++) if (trimmed[i] === "{") starts.push(i);
  for (let si = starts.length - 1; si >= 0; si--) {
    const start = starts[si]!;
    let depth = 0;
    for (let i = start; i < trimmed.length; i++) {
      const c = trimmed[i];
      if (c === "{") depth++;
      else if (c === "}") {
        depth--;
        if (depth === 0) {
          const slice = trimmed.slice(start, i + 1);
          if (!slice.includes('"orders"')) break;
          try {
            const parsed = JSON.parse(slice) as unknown;
            if (looksLikeProposal(parsed)) return parsed;
          } catch {
            break;
          }
        }
      }
    }
  }
  return null;
}

function normalizeOrders(raw: unknown): Order[] {
  if (!Array.isArray(raw)) return [];
  const orders: Order[] = [];
  for (const item of raw) {
    const o = asRecord(item);
    if (!o) continue;
    const side = String(o.side || "").toLowerCase();
    const symbol = String(o.symbol || "").toUpperCase();
    if (!symbol) continue;
    if (side === "buy") {
      orders.push({ side: "buy", symbol, notional_usd: Number(o.notional_usd) });
    } else if (side === "sell") {
      orders.push({ side: "sell", symbol, qty: Number(o.qty) });
    }
  }
  return orders;
}

export function toProposal(raw: Record<string, unknown>, asOf: string): Proposal {
  return {
    agent_id: "A1",
    as_of: typeof raw.as_of === "string" && raw.as_of ? raw.as_of : asOf,
    orders: normalizeOrders(raw.orders),
    thesis: typeof raw.thesis === "string" ? raw.thesis : "",
  };
}

export function readProposalFile(filePath: string, asOf: string): Proposal | null {
  if (!fs.existsSync(filePath)) return null;
  try {
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf8")) as unknown;
    if (!looksLikeProposal(parsed)) return null;
    return toProposal(parsed, asOf);
  } catch {
    return null;
  }
}

/** Prefer a file the agent wrote, then a write-tool payload, then JSON in the stream. */
export function recoverProposal(workDir: string, asOf: string, capture: StreamCapture): Proposal | null {
  const canonical = path.join(workDir, "A1.json");
  const existing = readProposalFile(canonical, asOf);
  if (existing) return existing;
  for (const w of capture.writes) {
    if (!w.path.replace(/\\/g, "/").endsWith("A1.json")) continue;
    try {
      const parsed = JSON.parse(w.fileText) as unknown;
      if (!looksLikeProposal(parsed)) continue;
      fs.mkdirSync(workDir, { recursive: true });
      fs.writeFileSync(canonical, JSON.stringify(parsed, null, 2));
      return toProposal(parsed, asOf);
    } catch {
      /* try the next write */
    }
  }
  const fromText = extractProposalJson(capture.text);
  if (!fromText) return null;
  fs.mkdirSync(workDir, { recursive: true });
  fs.writeFileSync(canonical, JSON.stringify(fromText, null, 2));
  return toProposal(fromText, asOf);
}
