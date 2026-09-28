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

export function hourlyDir(day: string, hour: number | string, root = storeRoot()): string {
  const hh = String(hour).padStart(2, "0");
  return path.join(stateDir(root), "hourly", day, hh);
}

export function hourlyNewsPath(day: string, hour: number | string, root = storeRoot()): string {
  return path.join(hourlyDir(day, hour, root), "news.json");
}

export function hourlyProposalPath(
  day: string,
  hour: number | string,
  agentId: string,
  root = storeRoot(),
): string {
  return path.join(hourlyDir(day, hour, root), `${agentId}.json`);
}

export function hourlyPackPath(
  day: string,
  hour: number | string,
  agentId: string,
  root = storeRoot(),
): string {
  return path.join(hourlyDir(day, hour, root), `${agentId}.md`);
}

export function hourlyConsensusPath(day: string, hour: number | string, root = storeRoot()): string {
  return path.join(hourlyDir(day, hour, root), "consensus.json");
}

export function schedulerStatusPath(root = storeRoot()): string {
  return path.join(stateDir(root), "scheduler", "status.json");
}

export const AGENT_IDS = ["A1", "A2", "A3", "A4", "A5"] as const;
export type AgentId = (typeof AGENT_IDS)[number];
