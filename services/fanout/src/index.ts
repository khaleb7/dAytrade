import fs from "node:fs";
import path from "node:path";
import {
  AGENT_IDS,
  asOfIso,
  fixturesDir,
  hourlyDir,
  hourlyPackPath,
  hourlyProposalPath,
  isoZ,
  promptsDir,
  readJson,
  rosterPath,
  storeRoot,
  writeJson,
  type Roster,
} from "@daytrade/shared";

export interface FanoutResult {
  as_of: string;
  mode: "sdk_local" | "fixtures";
  agents: {
    agent_id: string;
    model_id: string;
    status: string;
    agentId?: string;
    error?: string;
    path?: string;
  }[];
  finished_at: string;
}

function buildPrompt(agentId: string, day: string, hour: number): string {
  const system = fs.readFileSync(path.join(promptsDir(), "agent_system.md"), "utf8");
  const tier = fs.readFileSync(path.join(promptsDir(), `${agentId}.md`), "utf8");
  const packPath = hourlyPackPath(day, hour, agentId);
  const pack = fs.existsSync(packPath)
    ? fs.readFileSync(packPath, "utf8")
    : `(missing pack ${packPath})`;
  const outRel = path.relative(storeRoot(), hourlyProposalPath(day, hour, agentId));
  return [
    system,
    "",
    tier,
    "",
    pack,
    "",
    "## Output path (required)",
    "Write ONLY valid JSON (no markdown fences) to this file relative to the store cwd:",
    `\`${outRel}\``,
    "",
    `agent_id must be "${agentId}". as_of must match the pack. Empty orders are OK.`,
  ].join("\n");
}

export function copyFixtureProposals(day: string, hour: number): FanoutResult {
  const src = path.join(fixturesDir(), "hourly", "proposals");
  const dest = hourlyDir(day, hour);
  fs.mkdirSync(dest, { recursive: true });
  const [y, m, d] = day.split("-").map(Number);
  const dayDate = new Date(Date.UTC(y!, m! - 1, d!));
  const asOf = asOfIso(dayDate, hour);
  const agents: FanoutResult["agents"] = [];
  for (const aid of AGENT_IDS) {
    const from = path.join(src, `${aid}.json`);
    const to = hourlyProposalPath(day, hour, aid);
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

export async function fanoutLocalSdk(
  day: string,
  hour: number,
  opts: {
    fromFixtures?: boolean;
    timeoutMs?: number;
  } = {},
): Promise<FanoutResult> {
  if (opts.fromFixtures || !process.env.CURSOR_API_KEY) {
    if (!process.env.CURSOR_API_KEY && !opts.fromFixtures) {
      console.warn("[fanout] CURSOR_API_KEY unset — using fixture proposals");
    }
    return copyFixtureProposals(day, hour);
  }

  const roster = readJson<Roster>(rosterPath());
  const [y, m, d] = day.split("-").map(Number);
  const dayDate = new Date(Date.UTC(y!, m! - 1, d!));
  const asOf = asOfIso(dayDate, hour);
  const root = storeRoot();
  const timeoutMs = opts.timeoutMs ?? 20 * 60 * 1000;

  const sdk = await import("@cursor/sdk");
  const Agent = (sdk as unknown as { Agent: { create: (o: unknown) => Promise<SDKAgent> } }).Agent;

  const agentsOut: FanoutResult["agents"] = [];

  await Promise.all(
    AGENT_IDS.map(async (aid) => {
      const modelId = roster.agents[aid]?.model_id;
      if (!modelId) {
        agentsOut.push({ agent_id: aid, model_id: "?", status: "no_model" });
        return;
      }
      const prompt = buildPrompt(aid, day, hour);
      let agent: SDKAgent | undefined;
      try {
        agent = await Agent.create({
          apiKey: process.env.CURSOR_API_KEY,
          model: { id: modelId },
          local: { cwd: root },
        });
        const run = await agent.send(prompt);
        await Promise.race([
          (async () => {
            if (typeof run.wait === "function") await run.wait();
            else if (typeof run.stream === "function") {
              for await (const _ of run.stream()) {
                /* drain */
              }
            }
          })(),
          new Promise((_, rej) =>
            setTimeout(() => rej(new Error("fanout timeout")), timeoutMs),
          ),
        ]);
        const outPath = hourlyProposalPath(day, hour, aid);
        const status = fs.existsSync(outPath) ? "wrote" : "completed_no_file";
        agentsOut.push({
          agent_id: aid,
          model_id: modelId,
          status,
          agentId: agent.agentId,
          path: outPath,
        });
      } catch (e) {
        agentsOut.push({
          agent_id: aid,
          model_id: modelId,
          status: "error",
          error: e instanceof Error ? e.message : String(e),
          agentId: agent?.agentId,
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
    agents: agentsOut,
    finished_at: isoZ(),
  };
  writeJson(path.join(hourlyDir(day, hour), "fanout.json"), result);
  return result;
}

export { copyFixtureProposals as fanoutFixtures };
