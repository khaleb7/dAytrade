import * as fs from "node:fs";
import * as path from "node:path";
import {
  activeAgentIds,
  asOfIso,
  fixturesDir,
  hourlyDir,
  hourlyPackPath,
  hourlyProposalPath,
  isoZ,
  loadRoster,
  normalizeSlot,
  parseSlot,
  promptsDir,
  rosterPath,
  storeRoot,
  writeJson,
} from "@daytrade/shared";
import { drainSdkRun, ensureProposalFile } from "./proposalRecovery.js";

/** Default fan-out budget for 30m RTH ticks. */
export const DEFAULT_FANOUT_TIMEOUT_MS = 20 * 60 * 1000;

export interface FanoutResult {
  as_of: string;
  mode: "sdk_local" | "fixtures";
  started_at?: string;
  timeout_ms?: number;
  agents: {
    agent_id: string;
    model_id: string;
    status: string;
    agentId?: string;
    error?: string;
    path?: string;
    duration_ms?: number;
  }[];
  finished_at: string;
}

function buildPrompt(agentId: string, day: string, hourOrSlot: number | string): string {
  const system = fs.readFileSync(path.join(promptsDir(), "agent_system.md"), "utf8");
  const tier = fs.readFileSync(path.join(promptsDir(), `${agentId}.md`), "utf8");
  const packPath = hourlyPackPath(day, hourOrSlot, agentId);
  const pack = fs.existsSync(packPath)
    ? fs.readFileSync(packPath, "utf8")
    : `(missing pack ${packPath})`;
  const outAbs = hourlyProposalPath(day, hourOrSlot, agentId);
  const outRel = path.relative(storeRoot(), outAbs);
  return [
    system,
    "",
    tier,
    "",
    pack,
    "",
    "## Output path (required)",
    "You MUST persist the proposal with the Write tool (not chat-only).",
    "Write ONLY valid JSON (no markdown fences) to exactly this path:",
    `\`${outAbs}\``,
    `(relative to store cwd: \`${outRel}\`)`,
    "",
    `agent_id must be "${agentId}". as_of must match the pack. Empty orders are OK.`,
  ].join("\n");
}

export function copyFixtureProposals(day: string, hourOrSlot: number | string): FanoutResult {
  const src = path.join(fixturesDir(), "hourly", "proposals");
  const dest = hourlyDir(day, hourOrSlot);
  fs.mkdirSync(dest, { recursive: true });
  const [y, m, d] = day.split("-").map(Number);
  const dayDate = new Date(Date.UTC(y!, m! - 1, d!));
  const slot = normalizeSlot(hourOrSlot);
  const { hour, minute } = parseSlot(slot);
  const asOf = asOfIso(dayDate, hour, minute);
  const agents: FanoutResult["agents"] = [];
  for (const aid of activeAgentIds()) {
    const from = path.join(src, `${aid}.json`);
    const to = hourlyProposalPath(day, hourOrSlot, aid);
    if (fs.existsSync(from)) {
      fs.copyFileSync(from, to);
      agents.push({ agent_id: aid, model_id: "fixture", status: "copied", path: to });
    } else {
      agents.push({ agent_id: aid, model_id: "fixture", status: "missing_fixture" });
    }
  }
  const result: FanoutResult = {
    as_of: asOf,
    mode: "fixtures",
    agents,
    finished_at: isoZ(),
  };
  writeJson(path.join(dest, "fanout.json"), result);
  return result;
}

type SDKRun = {
  stream?: () => AsyncIterable<unknown>;
  wait?: () => Promise<unknown>;
};

type SDKAgent = {
  agentId: string;
  send: (msg: string) => Promise<SDKRun>;
  close?: () => void | Promise<void>;
};

/** Map Cursor IDE/subagent slugs to SDK Agent.create model ids.
 * Roster should use `grok-4.7` for trading fan-out (Composer is coding-only).
 * Legacy vendor/Composer suffixes are still stripped if an old roster slips through.
 */
export function normalizeModelId(raw: string): string {
  let id = (raw || "").trim();
  if (!id) return id;
  // Strip common thinking/effort suffixes used in IDE model pickers
  id = id.replace(/-thinking-(?:low|medium|high|max|xhigh|minimal)$/i, "");
  id = id.replace(/-(?:low|medium|high|max|xhigh|minimal|none|fast)$/i, "");
  const aliases: Record<string, string> = {
    // Cursor bucket
    "composer-2.5-medium": "composer-2.5",
    "composer-2-medium": "composer-2",
    // Legacy (should not be in roster; kept for old conflict files)
    "gpt-5.6-sol-medium": "gpt-5.6-sol",
    "claude-sonnet-5-thinking-medium": "claude-sonnet-5",
    "gemini-3.8-flash-medium": "gemini-3.8-flash",
    "claude-opus-5-thinking-medium": "claude-opus-5",
    "grok-4.7-medium": "grok-4.7",
  };
  return aliases[raw.trim()] || aliases[id] || id;
}

export async function fanoutLocalSdk(
  day: string,
  hourOrSlot: number | string,
  opts: {
    fromFixtures?: boolean;
    timeoutMs?: number;
  } = {},
): Promise<FanoutResult> {
  if (opts.fromFixtures || !process.env.CURSOR_API_KEY) {
    if (!process.env.CURSOR_API_KEY && !opts.fromFixtures) {
      console.warn("[fanout] CURSOR_API_KEY unset — using fixture proposals");
    }
    return copyFixtureProposals(day, hourOrSlot);
  }

  const roster = loadRoster();
  const aids = activeAgentIds(roster);
  console.log(`[fanout] roster=${rosterPath()} agents=${aids.join(",") || "(none)"}`);
  if (!aids.length) {
    throw new Error(`no agents with model_id in roster: ${rosterPath()}`);
  }
  const [y, m, d] = day.split("-").map(Number);
  const dayDate = new Date(Date.UTC(y!, m! - 1, d!));
  const slot = normalizeSlot(hourOrSlot);
  const { hour, minute } = parseSlot(slot);
  const asOf = asOfIso(dayDate, hour, minute);
  const root = storeRoot();
  // 30-min cadence: default 20 min fan-out budget
  const timeoutMs = opts.timeoutMs ?? DEFAULT_FANOUT_TIMEOUT_MS;
  const startedAt = isoZ();
  const startedMs = Date.now();
  console.log(`[fanout] timeout_ms=${timeoutMs} (~${Math.round(timeoutMs / 60000)}m)`);

  const sdk = await import("@cursor/sdk");
  const Agent = (sdk as unknown as { Agent: { create: (o: unknown) => Promise<SDKAgent> } }).Agent;

  const agentsOut: FanoutResult["agents"] = [];

  await Promise.all(
    aids.map(async (aid) => {
      const rawModel = roster.agents[aid]?.model_id || "";
      const modelId = normalizeModelId(rawModel);
      const t0 = Date.now();
      // activeAgentIds already requires model_id; empty after normalize is still a hard skip
      if (!modelId) {
        agentsOut.push({ agent_id: aid, model_id: "?", status: "no_model", duration_ms: 0 });
        return;
      }
      if (rawModel && rawModel !== modelId) {
        console.warn(`[fanout] ${aid}: normalized model ${rawModel} -> ${modelId}`);
      }
      const outPath = hourlyProposalPath(day, hourOrSlot, aid);
      fs.mkdirSync(path.dirname(outPath), { recursive: true });
      const prompt = buildPrompt(aid, day, hourOrSlot);
      let agent: SDKAgent | undefined;
      try {
        agent = await Agent.create({
          apiKey: process.env.CURSOR_API_KEY,
          model: { id: modelId },
          local: { cwd: root },
        });
        const run = await agent.send(prompt);
        const capture = await drainSdkRun(run, timeoutMs);
        const recovered = ensureProposalFile(outPath, aid, day, slot, asOf, capture);
        if (recovered.ok) {
          agentsOut.push({
            agent_id: aid,
            model_id: modelId,
            status: recovered.source === "existing" ? "wrote" : `wrote_${recovered.source}`,
            agentId: agent.agentId,
            path: outPath,
            duration_ms: Date.now() - t0,
          });
        } else {
          agentsOut.push({
            agent_id: aid,
            model_id: modelId,
            status: "error",
            error: recovered.error,
            agentId: agent.agentId,
            path: outPath,
            duration_ms: Date.now() - t0,
          });
        }
      } catch (e) {
        agentsOut.push({
          agent_id: aid,
          model_id: modelId,
          status: "error",
          error: e instanceof Error ? e.message : String(e),
          agentId: agent?.agentId,
          duration_ms: Date.now() - t0,
        });
      } finally {
        try {
          if (agent && typeof agent.close === "function") await agent.close();
        } catch {
          /* ignore dispose errors */
        }
      }
    }),
  );

  agentsOut.sort((a, b) => a.agent_id.localeCompare(b.agent_id));
  const result: FanoutResult = {
    as_of: asOf,
    mode: "sdk_local",
    started_at: startedAt,
    timeout_ms: timeoutMs,
    agents: agentsOut,
    finished_at: isoZ(),
  };
  console.log(
    `[fanout] done in ${Date.now() - startedMs}ms — ` +
      agentsOut.map((a) => `${a.agent_id}=${a.status}/${a.duration_ms ?? "?"}ms`).join(" "),
  );
  writeJson(path.join(hourlyDir(day, hourOrSlot), "fanout.json"), result);
  return result;
}

export { copyFixtureProposals as fanoutFixtures };
