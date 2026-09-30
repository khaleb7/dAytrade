#!/usr/bin/env node
/**
 * DayTrade hourly orchestrator CLI.
 *
 * Replaces scripts/hourly_scheduler.py as the primary RTH entrypoint.
 *
 * Usage:
 *   npx tsx src/cli.ts --hour 2026-09-25T14 --phase prep --from-fixtures
 *   npx tsx src/cli.ts --loop --phase prep-then-settle --catch-up
 *   node dist/cli.js --hour … --phase settle
 *   node dist/cli.js --hour … --phase settle --dry-run
 */
import { formatDay, loadEnvFile } from "@daytrade/shared";
import { nextRthTickClean, runHour, runLoop, type Phase } from "./index.js";

function usage(): never {
  console.error(`usage:
  daytrade-orchestrator --hour YYYY-MM-DDTHH:MM [--phase prep|fanout|settle|full|prep-then-settle|day-end]
                        [--dry-run] [--skip-ingest] [--from-fixtures] [--allow-non-rth]
                        [--proposal-wait-minutes N] [--env-file PATH]
  daytrade-orchestrator --loop [--phase …] [--catch-up] [--dry-run] …
  daytrade-orchestrator --next-tick

  RTH half-hour ticks 09:30–15:30 ET. Paper submit ON by default (--dry-run to skip).
  After 15:30 settle, day-end analysis is written for next-session packs.`);
  process.exit(1);
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  if (!args.length) usage();

  let hour: string | undefined;
  let phase: Phase = "prep-then-settle";
  // Paper account: submit by default; --dry-run to opt out
  let submit = true;
  let skipIngest = false;
  let fromFixtures = false;
  let allowNonRth = false;
  let proposalWaitMinutes: number | undefined;
  let envFile: string | undefined;
  let loop = false;
  let catchUp = false;
  let once = false;
  let nextTickOnly = false;

  for (let i = 0; i < args.length; i++) {
    const a = args[i]!;
    if (a === "--hour" && args[i + 1]) hour = args[++i];
    else if (a === "--phase" && args[i + 1]) phase = args[++i] as Phase;
    else if (a === "--submit") submit = true;
    else if (a === "--dry-run" || a === "--no-submit") submit = false;
    else if (a === "--skip-ingest") skipIngest = true;
    else if (a === "--from-fixtures") fromFixtures = true;
    else if (a === "--allow-non-rth") allowNonRth = true;
    else if (a === "--proposal-wait-minutes" && args[i + 1]) {
      proposalWaitMinutes = parseInt(args[++i]!, 10);
    } else if (a === "--env-file" && args[i + 1]) envFile = args[++i];
    else if (a === "--loop") loop = true;
    else if (a === "--catch-up") catchUp = true;
    else if (a === "--once") once = true;
    else if (a === "--next-tick") nextTickOnly = true;
    else if (a === "-h" || a === "--help") usage();
    else if (!a.startsWith("-") && !hour) hour = a;
    else {
      console.error(`unknown arg: ${a}`);
      usage();
    }
  }

  loadEnvFile(envFile);
  // CLI flag wins; else DAYTRADE_PROPOSAL_WAIT_MINUTES; else 20
  if (proposalWaitMinutes === undefined) {
    const fromEnv = parseInt(process.env.DAYTRADE_PROPOSAL_WAIT_MINUTES || "", 10);
    proposalWaitMinutes = Number.isFinite(fromEnv) && fromEnv >= 0 ? fromEnv : 20;
  }

  if (nextTickOnly) {
    const n = nextRthTickClean();
    console.log(
      JSON.stringify(
        {
          bucket: n.bucket,
          slot: n.slot,
          when: n.when.toISOString(),
          day: formatDay(n.day),
          hour: n.hour,
          minute: n.minute,
        },
        null,
        2,
      ),
    );
    return;
  }

  if (loop && !once) {
    await runLoop({
      phase,
      submit,
      catchUp,
      proposalWaitMinutes,
      envFile,
    });
    return;
  }

  if (!hour) {
    if (once || catchUp) {
      const n = nextRthTickClean();
      hour = n.bucket;
      console.error(`[orchestrator] --once using next bucket ${hour}`);
    } else {
      usage();
    }
  }

  const report = await runHour({
    hour: hour!,
    phase,
    submit,
    skipIngest,
    fromFixtures,
    allowNonRth,
    proposalWaitMinutes,
    envFile,
  });
  console.log(JSON.stringify(report, null, 2));
  if (report.error) process.exit(2);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
