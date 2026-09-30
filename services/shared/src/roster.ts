import { rosterPath } from "./paths.js";
import { readJson } from "./env.js";
import type { Roster } from "./types.js";

/** Fallback when roster is missing/unreadable — single-agent cutover default. */
export const DEFAULT_ACTIVE_AGENT_IDS = ["A1"] as const;

export function loadRoster(root?: string): Roster {
  return readJson<Roster>(rosterPath(root));
}

/**
 * Agents to fan out / pack / settle for: keys in `state/roster.json` with a non-empty `model_id`.
 * Sorted for stable logs. Does **not** use a hard-coded A1–A5 list.
 */
export function activeAgentIds(roster?: Roster, root?: string): string[] {
  let r: Roster;
  try {
    r = roster ?? loadRoster(root);
  } catch {
    return [...DEFAULT_ACTIVE_AGENT_IDS];
  }
  const agents = r?.agents;
  if (!agents || typeof agents !== "object") {
    return [...DEFAULT_ACTIVE_AGENT_IDS];
  }
  const ids = Object.keys(agents)
    .filter((aid) => {
      const mid = agents[aid]?.model_id;
      return typeof mid === "string" && mid.trim().length > 0;
    })
    .sort((a, b) => a.localeCompare(b));
  return ids.length ? ids : [...DEFAULT_ACTIVE_AGENT_IDS];
}
