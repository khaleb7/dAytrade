import * as fs from "node:fs";
import * as path from "node:path";
import { stateDir, writeJson } from "@daytrade/shared";

export type StreamCapture = {
  text: string;
  writes: { path: string; fileText: string }[];
};

type SDKRun = {
  stream?: () => AsyncIterable<unknown>;
  wait?: () => Promise<unknown>;
};

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : null;
}

/** Accumulate SDK stream events (text + write tool payloads). */
export function absorbStreamEvent(ev: unknown, cap: StreamCapture): void {
  const o = asRecord(ev);
  if (!o) return;
  if (o.type === "text-delta" && typeof o.text === "string") {
    cap.text += o.text;
  }
  const tc = asRecord(o.toolCall);
  if (tc?.type === "write") {
    const args = asRecord(tc.args);
    const p = args?.path;
    const fileText = args?.fileText;
    if (typeof p === "string" && typeof fileText === "string") {
      cap.writes.push({ path: p, fileText });
    }
  }
}

export async function drainSdkRun(run: SDKRun, timeoutMs: number): Promise<StreamCapture> {
  const cap: StreamCapture = { text: "", writes: [] };
  const work = async () => {
    if (typeof run.stream === "function") {
      for await (const ev of run.stream()) absorbStreamEvent(ev, cap);
    } else if (typeof run.wait === "function") {
      await run.wait();
    }
  };
  await Promise.race([
    work(),
    new Promise((_, rej) => setTimeout(() => rej(new Error("fanout timeout")), timeoutMs)),
  ]);
  return cap;
}

function normPath(p: string): string {
  return p.replace(/\\/g, "/");
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
      /* try next */
    }
  }
  // Last balanced `{ ... }` objects containing "orders"
  const starts: number[] = [];
  for (let i = 0; i < trimmed.length; i++) {
    if (trimmed[i] === "{") starts.push(i);
  }
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

function findHourlyProposalFiles(day: string, agentId: string): string[] {
  const base = path.join(stateDir(), "hourly", day);
  if (!fs.existsSync(base)) return [];
  const hits: string[] = [];
  const walk = (dir: string) => {
    let entries: string[];
    try {
      entries = fs.readdirSync(dir);
    } catch {
      return;
    }
    for (const name of entries) {
      const full = path.join(dir, name);
      let st;
      try {
        st = fs.statSync(full);
      } catch {
        continue;
      }
      if (st.isDirectory()) walk(full);
      else if (name === `${agentId}.json`) hits.push(full);
    }
  };
  walk(base);
  return hits;
}

function proposalPathMatches(p: string, agentId: string, day: string, slot: string): boolean {
  const n = normPath(p);
  return (
    n.endsWith(`/${day}/${slot}/${agentId}.json`) ||
    n.endsWith(`state/hourly/${day}/${slot}/${agentId}.json`) ||
    n.endsWith(`/${agentId}.json`)
  );
}

export type RecoverResult =
  | { ok: true; source: "existing" | "write_tool" | "relocated" | "stream_json" }
  | { ok: false; error: string };

/** Ensure canonical proposal path exists; recover from SDK write tool / misplaced file / stream JSON. */
export function ensureProposalFile(
  outPath: string,
  agentId: string,
  day: string,
  slot: string,
  asOf: string,
  capture: StreamCapture,
): RecoverResult {
  if (fs.existsSync(outPath)) {
    try {
      const raw = fs.readFileSync(outPath, "utf8");
      const parsed = JSON.parse(raw) as unknown;
      if (looksLikeProposal(parsed)) return { ok: true, source: "existing" };
    } catch {
      /* fall through — try to repair */
    }
  }

  fs.mkdirSync(path.dirname(outPath), { recursive: true });

  for (const w of capture.writes) {
    if (!proposalPathMatches(w.path, agentId, day, slot) && !w.path.endsWith(`${agentId}.json`)) {
      continue;
    }
    try {
      const parsed = JSON.parse(w.fileText) as unknown;
      if (!looksLikeProposal(parsed)) continue;
      parsed.agent_id = agentId;
      if (!parsed.as_of) parsed.as_of = asOf;
      writeJson(outPath, parsed);
      return { ok: true, source: "write_tool" };
    } catch {
      fs.writeFileSync(outPath, w.fileText, "utf8");
      return { ok: true, source: "write_tool" };
    }
  }

  for (const hit of findHourlyProposalFiles(day, agentId)) {
    if (path.resolve(hit) === path.resolve(outPath)) continue;
    if (!normPath(hit).includes(`/${day}/`)) continue;
    try {
      fs.copyFileSync(hit, outPath);
      return { ok: true, source: "relocated" };
    } catch {
      /* continue */
    }
  }

  const fromText = extractProposalJson(capture.text);
  if (fromText) {
    fromText.agent_id = agentId;
    if (!fromText.as_of) fromText.as_of = asOf;
    writeJson(outPath, fromText);
    return { ok: true, source: "stream_json" };
  }

  return {
    ok: false,
    error: `SDK finished but ${agentId}.json missing at ${outPath} (no write tool / stream JSON recovery)`,
  };
}
