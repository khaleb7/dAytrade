import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** Store root: DAYTRADE_STORE or two levels up from services/shared */
export function storeRoot(): string {
  const env = process.env["DAYTRADE_STORE"];
  if (env && fs.existsSync(env)) return path.resolve(env);
  // services/shared/src -> store
  return path.resolve(__dirname, "../../..");
}

export function stateDir(root = storeRoot()): string {
  return path.join(root, "state");
}

export function scriptsDir(root = storeRoot()): string {
  return path.join(root, "scripts");
}

export function promptsDir(root = storeRoot()): string {
  return path.join(root, "prompts");
}

export function fixturesDir(root = storeRoot()): string {
  return path.join(root, "fixtures");
}

export function rosterPath(root = storeRoot()): string {
  return path.join(stateDir(root), "roster.json");
}

export function bookPortfolioPath(root = storeRoot()): string {
  return path.join(stateDir(root), "book", "portfolio.json");
}

export function alpacaConfigPath(root = storeRoot()): string {
  return path.join(stateDir(root), "alpaca", "config.json");
}

export function lessonsPath(root = storeRoot()): string {
  return path.join(stateDir(root), "lessons", "ledger.jsonl");
}

export function signalsDir(root = storeRoot()): string {
  return path.join(stateDir(root), "signals");
}

export function signalsLatestPath(root = storeRoot()): string {
  return path.join(signalsDir(root), "latest.json");
}

/** Slot dir key: HHMM (0930, 1400). Legacy 2-digit hour dirs still resolved as fallback. */
export function hourlyDir(day: string, hourOrSlot: number | string, root = storeRoot()): string {
  const slot = normalizeHourlySlot(hourOrSlot);
  const primary = path.join(stateDir(root), "hourly", day, slot);
  if (fs.existsSync(primary)) return primary;
  // Legacy hour-only dirs (e.g. "14") for historical reads
  if (slot.endsWith("00")) {
    const legacy = path.join(stateDir(root), "hourly", day, slot.slice(0, 2));
    if (fs.existsSync(legacy)) return legacy;
  }
  return primary;
}

function normalizeHourlySlot(hourOrSlot: number | string): string {
  if (typeof hourOrSlot === "number") {
    return `${String(hourOrSlot).padStart(2, "0")}00`;
  }
  const raw = String(hourOrSlot).trim();
  if (/^\d{4}$/.test(raw)) return raw;
  if (/^\d{1,2}$/.test(raw)) return `${raw.padStart(2, "0")}00`;
  const m = raw.match(/^(\d{1,2})[:\-](\d{2})$/);
  if (m) return `${m[1]!.padStart(2, "0")}${m[2]}`;
  return raw;
}

export function hourlyNewsPath(day: string, hourOrSlot: number | string, root = storeRoot()): string {
  return path.join(hourlyDir(day, hourOrSlot, root), "news.json");
}

export function hourlyProposalPath(
  day: string,
  hourOrSlot: number | string,
  agentId: string,
  root = storeRoot(),
): string {
  return path.join(hourlyDir(day, hourOrSlot, root), `${agentId}.json`);
}

export function hourlyPackPath(
  day: string,
  hourOrSlot: number | string,
  agentId: string,
  root = storeRoot(),
): string {
  return path.join(hourlyDir(day, hourOrSlot, root), `${agentId}.md`);
}

export function hourlyConsensusPath(
  day: string,
  hourOrSlot: number | string,
  root = storeRoot(),
): string {
  return path.join(hourlyDir(day, hourOrSlot, root), "consensus.json");
}

export function hourlySignalsPath(
  day: string,
  hourOrSlot: number | string,
  root = storeRoot(),
): string {
  return path.join(hourlyDir(day, hourOrSlot, root), "signals.json");
}

export function dailyDir(day: string, root = storeRoot()): string {
  return path.join(stateDir(root), "daily", day);
}

export function dayEndAnalysisPath(day: string, root = storeRoot()): string {
  return path.join(dailyDir(day), "analysis.json");
}

export function schedulerStatusPath(root = storeRoot()): string {
  return path.join(stateDir(root), "scheduler", "status.json");
}

/**
 * @deprecated Prefer `activeAgentIds()` from `@daytrade/shared` (roster-driven).
 * Kept as a compile-time fallback constant matching single-agent A1 cutover.
 */
export const AGENT_IDS = ["A1"] as const;
export type AgentId = (typeof AGENT_IDS)[number];
