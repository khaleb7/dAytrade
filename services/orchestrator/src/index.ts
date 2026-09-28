import * as fs from "node:fs";
import * as path from "node:path";
import {
  credentialsPresent,
  reconcile,
  submitConsensusOrders,
  validateBook,
} from "@daytrade/book";
import { buildConsensus, loadProposals, writeConsensus } from "@daytrade/consensus";
import { fanoutLocalSdk } from "@daytrade/fanout";
import { buildHour } from "@daytrade/news-bridge";
import { buildHourlyPacks } from "@daytrade/packs";
import {
  AGENT_IDS,
  bookPortfolioPath,
  bucketFor,
  etOffsetHours,
  fixturesDir,
  formatDay,
  hourlyDir,
  isRthConsensusHour,
  isTradingDay,
  isoZ,
  loadEnvFile,
  nextTradingDay,
  parseHourBucket,
  RTH_HOURS,
  readJson,
  schedulerStatusPath,
  writeJson,
  type BookPortfolio,
  type ConsensusResult,
} from "@daytrade/shared";

export type Phase = "prep" | "fanout" | "settle" | "full" | "prep-then-settle";

export interface RunOptions {
  hour: string;
  phase?: Phase;
  submit?: boolean;
  skipIngest?: boolean;
  fromFixtures?: boolean;
  allowNonRth?: boolean;
  proposalWaitMinutes?: number;
  envFile?: string;
}

function proposalsReady(day: string, hour: number): boolean {
  const dir = hourlyDir(day, hour);
  return AGENT_IDS.every((a) => fs.existsSync(path.join(dir, `${a}.json`)));
}

function writeStatus(payload: Record<string, unknown>): void {
  writeJson(schedulerStatusPath(), payload);
}

export async function runHour(opts: RunOptions): Promise<Record<string, unknown>> {
  loadEnvFile(opts.envFile);
  const phase: Phase = opts.phase || "full";
  const { day, hour, asOf } = parseHourBucket(opts.hour);
  const dayStr = formatDay(day);
  const outDir = hourlyDir(dayStr, hour);
  fs.mkdirSync(outDir, { recursive: true });

  const report: Record<string, unknown> = {
    as_of: asOf,
    day: dayStr,
    hour_et: String(hour).padStart(2, "0"),
    phase,
    started_at: isoZ(),
    dry_run: !opts.submit,
    steps: {} as Record<string, unknown>,
  };
  const steps = report.steps as Record<string, unknown>;

  if (!opts.allowNonRth && !isRthConsensusHour(day, hour)) {
    report.error = `${asOf} outside RTH consensus hours (10-15 ET trading day)`;
    writeJson(path.join(outDir, "settle.json"), report);
    return report;
  }

  const doPrep = phase === "prep" || phase === "full" || phase === "prep-then-settle";
  const doFanout =
    phase === "fanout" || phase === "full" || phase === "prep-then-settle";
  const doSettle =
    phase === "settle" || phase === "full" || phase === "prep-then-settle";

  if (doPrep) {
    try {
      steps.news = await buildHour(opts.hour, {
        skipIngest: opts.skipIngest,
        fromFixtures: opts.fromFixtures,
        allowNonRth: opts.allowNonRth,
      });
    } catch (e) {
      steps.news = { error: e instanceof Error ? e.message : String(e) };
      if (!opts.fromFixtures) {
        report.error = "news build failed";
        writeJson(path.join(outDir, "settle.json"), report);
        return report;
      }
    }

    if (credentialsPresent()) {
      try {
        const mirror = await reconcile();
        steps.reconcile = {
          equity_usd: mirror.equity_usd,
          sizing_equity_usd: mirror.sizing_equity_usd,
          positions: mirror.positions.length,
        };
      } catch (e) {
        steps.reconcile = { error: e instanceof Error ? e.message : String(e) };
      }
    } else {
      steps.reconcile = { skipped: true, reason: "no_credentials" };
    }

    const packs = buildHourlyPacks(dayStr, hour);
    steps.packs = { wrote: packs };

    const ready = {
      as_of: asOf,
      day: dayStr,
      hour_et: String(hour).padStart(2, "0"),
      packs,
      ready_at: isoZ(),
      next: "fanout then settle",
    };
    writeJson(path.join(outDir, "ready.json"), ready);
    steps.ready = ready;

    if (phase === "prep") {
      report.finished_at = isoZ();
      writeJson(path.join(outDir, "settle.json"), report);
      writeStatus({ ...ready, phase: "prep" });
      return report;
    }
  }

  if (doFanout) {
    const waitMin = opts.proposalWaitMinutes ?? 20;
    if (opts.fromFixtures) {
      steps.fanout = await fanoutLocalSdk(dayStr, hour, { fromFixtures: true });
    } else if (phase === "fanout" || phase === "full" || phase === "prep-then-settle") {
      steps.fanout = await fanoutLocalSdk(dayStr, hour, {
        fromFixtures: false,
        timeoutMs: Math.max(60_000, waitMin * 60_000),
      });
    }

    if (phase === "fanout") {
      report.finished_at = isoZ();
      writeJson(path.join(outDir, "settle.json"), report);
      return report;
    }
  }

  if (doSettle) {
    if (!proposalsReady(dayStr, hour)) {
      if (opts.fromFixtures) {
        await fanoutLocalSdk(dayStr, hour, { fromFixtures: true });
      } else {
        steps.settle = { skipped: true, reason: "proposals_missing" };
        report.finished_at = isoZ();
        writeJson(path.join(outDir, "settle.json"), report);
        writeStatus({
          bucket: bucketFor(day, hour),
          settle_skipped: "proposals_missing",
          finished_at: isoZ(),
        });
        return report;
      }
    }

    const { loaded, missing } = loadProposals(dayStr, hour);
    let book: BookPortfolio = { cash_usd: 1000, equity_usd: 1000, positions: [] };
    if (fs.existsSync(bookPortfolioPath())) {
      book = readJson<BookPortfolio>(bookPortfolioPath());
    }
    const held: Record<string, number> = {};
    for (const p of book.positions || []) held[p.symbol] = Number(p.qty);
    const consensus: ConsensusResult = buildConsensus(loaded, {
      asOf,
      heldQty: held,
    });
    if (missing.length) consensus.missing_agents = missing;
    const cpath = writeConsensus(dayStr, hour, consensus);
    steps.consensus = {
      wrote: cpath,
      orders: consensus.orders,
      no_consensus: consensus.no_consensus,
    };

    let prices: Record<string, number> | undefined;
    const pricesPath = path.join(fixturesDir(), "hourly", "prices.json");
    if (fs.existsSync(pricesPath)) prices = readJson(pricesPath);
    const validation = validateBook(consensus, book, prices);
    steps.validate = validation;

    if (!validation.ok) {
      steps.submit = { skipped: true, reason: "validation_failed" };
    } else if (consensus.no_consensus || !consensus.orders.length) {
      steps.submit = { skipped: true, reason: "no_consensus" };
    } else {
      const results = await submitConsensusOrders(consensus.orders, {
        dryRun: !opts.submit,
      });
      steps.submit = {
        dry_run: !opts.submit,
        orders: results,
        note: opts.submit
          ? "submitted to Alpaca paper"
          : "Pass --submit to place Alpaca paper market orders",
      };
      if (opts.submit && credentialsPresent()) {
        try {
          const mirror = await reconcile();
          steps.post_reconcile = {
            equity_usd: mirror.equity_usd,
            cash_usd: mirror.cash_usd,
          };
        } catch (e) {
          steps.post_reconcile = { error: e instanceof Error ? e.message : String(e) };
        }
      }
    }
  }

  report.finished_at = isoZ();
  writeJson(path.join(outDir, "settle.json"), report);
  writeStatus({
    bucket: bucketFor(day, hour),
    as_of: asOf,
    phase,
    finished_at: report.finished_at,
  });
  return report;
}

function nowEtParts(): { day: Date; hour: number; minute: number } {
  const now = new Date();
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const parts = Object.fromEntries(fmt.formatToParts(now).map((p) => [p.type, p.value]));
  const day = new Date(Date.UTC(+parts.year!, +parts.month! - 1, +parts.day!));
  let hour = parseInt(parts.hour!, 10);
  if (hour === 24) hour = 0;
  const minute = parseInt(parts.minute!, 10);
  return { day, hour, minute };
}

export function nextRthTickClean(): {
  day: Date;
  hour: number;
  when: Date;
  bucket: string;
} {
  const { day: etDay, hour: etHour, minute } = nowEtParts();
  let d = new Date(etDay);
  for (let n = 0; n < 20; n++) {
    if (isTradingDay(d)) {
      for (const h of RTH_HOURS) {
        const sameDay = formatDay(d) === formatDay(etDay);
        if (sameDay && (h < etHour || (h === etHour && minute > 0))) continue;
        const off = etOffsetHours(d);
        const when = new Date(
          Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), h + off, 0, 0),
        );
        return { day: d, hour: h, when, bucket: bucketFor(d, h) };
      }
    }
    d = nextTradingDay(d);
  }
  throw new Error("could not find next RTH tick");
}

/** @deprecated prefer nextRthTickClean */
export function nextRthTick(): { day: Date; hour: number; when: Date } {
  const n = nextRthTickClean();
  return { day: n.day, hour: n.hour, when: n.when };
}

export async function sleepUntil(when: Date, wakeEverySec = 30): Promise<void> {
  while (Date.now() < when.getTime()) {
    const remaining = when.getTime() - Date.now();
    await new Promise((r) =>
      setTimeout(r, Math.min(wakeEverySec * 1000, Math.max(1000, remaining))),
    );
  }
}

export async function runLoop(opts: {
  phase?: Phase;
  submit?: boolean;
  catchUp?: boolean;
  proposalWaitMinutes?: number;
  envFile?: string;
}): Promise<void> {
  loadEnvFile(opts.envFile);
  console.log("[orchestrator] loop started (Ctrl+C to stop)");
  if (opts.catchUp) {
    const { day, hour, minute } = nowEtParts();
    if (isTradingDay(day) && (RTH_HOURS as readonly number[]).includes(hour) && minute < 55) {
      console.log(`[orchestrator] catch-up current hour ${hour}`);
      await runHour({
        hour: bucketFor(day, hour),
        phase: opts.phase || "prep-then-settle",
        submit: opts.submit,
        proposalWaitMinutes: opts.proposalWaitMinutes,
        envFile: opts.envFile,
      });
    }
  }
  while (true) {
    const next = nextRthTickClean();
    writeStatus({
      next_tick: next.when.toISOString(),
      bucket: next.bucket,
      mode: "loop",
      updated_at: new Date().toISOString(),
    });
    console.log(`[orchestrator] next tick ${next.when.toISOString()} (${next.bucket})`);
    await sleepUntil(next.when);
    await new Promise((r) => setTimeout(r, 1000));
    try {
      const report = await runHour({
        hour: next.bucket,
        phase: opts.phase || "prep-then-settle",
        submit: opts.submit,
        proposalWaitMinutes: opts.proposalWaitMinutes ?? 20,
        envFile: opts.envFile,
      });
      console.log(JSON.stringify({ finished: report.finished_at, error: report.error }, null, 2));
    } catch (e) {
      console.error("[orchestrator] tick error:", e);
      writeStatus({ error: String(e), at: isoZ() });
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
}
