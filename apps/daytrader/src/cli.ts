import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { notifyDiscord } from "./discord.js";
import { runTick } from "./tick.js";

function promptsDir(): string {
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../prompts");
}

async function main(): Promise<void> {
  const newstrackerUrl = process.env.NEWSTRACKER_URL || "";
  if (!newstrackerUrl) {
    console.error("[daytrader] NEWSTRACKER_URL is required");
    process.exit(1);
  }
  const waitMin = Number(process.env.DAYTRADE_PROPOSAL_WAIT_MINUTES || "20");
  await notifyDiscord("Daytrader started", "Cron tick process is up.", true);
  const code = await runTick({
    newstrackerUrl,
    workDir: process.env.DAYTRADE_WORK || "/work",
    promptsDir: promptsDir(),
    modelId: process.env.DAYTRADE_MODEL || "grok-4.7",
    timeoutMs: (Number.isFinite(waitMin) && waitMin > 0 ? waitMin : 20) * 60 * 1000,
    dryRun: process.env.DAYTRADE_DRY_RUN === "1",
  });
  process.exit(code);
}

main().catch((err) => {
  console.error(`[daytrader] ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});
