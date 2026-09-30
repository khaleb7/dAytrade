import * as fs from "node:fs";
import * as path from "node:path";
import { spawnSync } from "node:child_process";
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
  activeAgentIds,
  bookPortfolioPath,
  bucketFor,
  fixturesDir,
  formatDay,
  hourlyDir,
  isRthConsensusTick,
  isTradingDay,
  isoZ,
  loadEnvFile,
  nextRthTickFrom,
  notifyDiscordFireAndForget,
  parseHourBucket,
  RTH_TICKS,
  readJson,
  schedulerStatusPath,
  scriptsDir,
  writeJson,
  type BookPortfolio,
  type ConsensusResult,
} from "@daytrade/shared";

export type Phase =
  | "prep"
  | "fanout"
  | "settle"
  | "full"
  | "prep-then-settle"
  | "day-end";

export interface RunOptions {
  hour: string;
  phase?: Phase;
  submit?: boolean;
  skipIngest?: boolean;
  fromFixtures?: boolean;
  allowNonRth?: boolean;
  /** Default 20 for 30-min cadence. Override via DAYTRADE_PROPOSAL_WAIT_MINUTES. */
  proposalWaitMinutes?: number;
  envFile?: string;
}

function proposalsReady(day: string, slot: string): boolean {
  const dir = hourlyDir(day, slot);
  const aids = activeAgentIds();
  if (!aids.length) return false;
  return aids.every((a) => fs.existsSync(path.join(dir, `${a}.json`)));
}

function writeStatus(payload: Record<string, unknown>): void {
  writeJson(schedulerStatusPath(), payload);
}

/** Fan-out / proposal wait: explicit CLI > env > 20m default (fits 30m ticks). */
function resolveProposalWaitMinutes(explicit?: number): number {
  if (typeof explicit === "number" && Number.isFinite(explicit) && explicit >= 0) {
    return explicit;
  }
  const fromEnv = parseInt(process.env.DAYTRADE_PROPOSAL_WAIT_MINUTES || "", 10);
  if (Number.isFinite(fromEnv) && fromEnv >= 0) return fromEnv;
  return 20;
}

function summarizeOrders(orders: unknown): string {
  if (!Array.isArray(orders) || !orders.length) return "none";
  return orders
    .slice(0, 8)
    .map((o) => {
      const x = o as Record<string, unknown>;
      const votes = typeof x.votes === "number" ? ` (${x.votes}v` : "";
      const agents = Array.isArray(x.agents)
        ? `:${(x.agents as string[]).join(",")}`
        : "";
      const voteBit = votes ? `${votes}${agents})` : "";
      if (x.side === "buy") return `buy ${x.symbol} $${x.notional_usd}${voteBit}`;
      return `sell ${x.symbol} qty=${x.qty}${voteBit}`;
    })
    .join("\n");
}

function summarizeRejectedLegs(legs: unknown): string {
  if (!Array.isArray(legs) || !legs.length) return "";
  return legs
    .slice(0, 8)
    .map((leg) => {
      const x = leg as Record<string, unknown>;
      if (x.reason === "below_majority") {
        const agents = Array.isArray(x.agents) ? (x.agents as string[]).join(",") : "";
        return `${x.side} ${x.symbol} ${x.votes ?? "?"}v${agents ? ` (${agents})` : ""} — below majority`;
      }
      return `${x.reason || "rejected"}${x.symbol ? ` ${x.symbol}` : ""}${x.agent ? ` @${x.agent}` : ""}`;
    })
    .join("\n");
}

/** Discord body for settle consensus (+ optional submit line already separate). */
function formatConsensusDiscordBody(consensus: {
  orders?: unknown[];
  no_consensus?: boolean;
  rejected_legs?: unknown[];
  proposals_loaded?: string[];
  min_votes?: number;
  missing_agents?: string[];
}): string {
  const lines: string[] = [];
  const minVotes = consensus.min_votes ?? 2;
  const loaded = Array.isArray(consensus.proposals_loaded)
    ? consensus.proposals_loaded.join(",")
    : "";
  if (loaded) lines.push(`loaded: ${loaded} · min_votes≥${minVotes}`);
  if (consensus.missing_agents?.length) {
    lines.push(`missing: ${consensus.missing_agents.join(",")}`);
  }
  if (consensus.no_consensus || !consensus.orders?.length) {
    const isHold = (consensus.min_votes ?? 1) <= 1;
    lines.push(isHold ? "result: hold (no orders)" : "result: no_consensus");
    const rejected = summarizeRejectedLegs(consensus.rejected_legs);
    if (rejected) {
      lines.push("rejected legs:");
      lines.push(rejected);
    } else if (isHold) {
      lines.push("(single agent chose empty orders — valid hold)");
    } else {
      lines.push("(no majority legs — typically all holds)");
    }
  } else {
    lines.push("orders:");
    lines.push(summarizeOrders(consensus.orders));
  }
  return lines.join("\n").slice(0, 1800);
}

function notifyTickOutcome(
  bucket: string,
  report: Record<string, unknown>,
): void {
  const steps = (report.steps || {}) as Record<string, unknown>;
  const err = report.error ? String(report.error) : "";
  const news = steps.news as { error?: string } | undefined;
  const fanout = steps.fanout as
    | { agents?: { agent_id: string; status: string; error?: string }[]; mode?: string }
    | undefined;
  const consensus = steps.consensus as
    | {
        orders?: unknown[];
        no_consensus?: boolean;
        rejected_legs?: unknown[];
        proposals_loaded?: string[];
        min_votes?: number;
        missing_agents?: string[];
      }
    | undefined;
  const submit = steps.submit as
    | { skipped?: boolean; reason?: string; dry_run?: boolean; orders?: unknown[]; error?: string; note?: string }
    | undefined;
  const settle = steps.settle as { skipped?: boolean; reason?: string } | undefined;
  const dayEnd = steps.day_end as { error?: string; stats?: Record<string, unknown> } | undefined;

  if (news?.error) {
    notifyDiscordFireAndForget({
      title: `Issue · news · ${bucket}`,
      body: news.error,
      kind: "issue",
      ok: false,
    });
  }
  if (fanout?.agents) {
    // Only flag real fan-out failures — never treat absent/retired agents as issues.
    // `no_model` should not appear for roster agents; if it does, still ignore (not a missing proposal).
    const bad = fanout.agents.filter(
      (a) => a.status === "error" || a.status === "completed_no_file" || a.status.startsWith("error"),
    );
    if (bad.length) {
      notifyDiscordFireAndForget({
        title: `Issue · fan-out · ${bucket}`,
        body: bad.map((a) => `${a.agent_id}: ${a.status}${a.error ? ` (${a.error})` : ""}`).join("\n"),
        kind: "issue",
        ok: false,
      });
    }
  }
  if (settle?.skipped) {
    notifyDiscordFireAndForget({
      title: `Issue · settle skipped · ${bucket}`,
      body: settle.reason || "skipped",
      kind: "issue",
      ok: false,
    });
  }
  if (consensus) {
    const orderCount = Array.isArray(consensus.orders) ? consensus.orders.length : 0;
    const rejectedCount = Array.isArray(consensus.rejected_legs)
      ? consensus.rejected_legs.length
      : 0;
    const isHold = !orderCount && (consensus.min_votes ?? 1) <= 1;
    notifyDiscordFireAndForget({
      title: isHold
        ? `Proposal · hold · ${bucket}`
        : orderCount
          ? `Proposal · ${orderCount} order(s) · ${bucket}`
          : `Proposal · no_consensus · ${bucket}`,
      body: formatConsensusDiscordBody(consensus),
      kind: "consensus",
      ok: Boolean(orderCount) || isHold,
      fields: [
        { name: "orders", value: String(orderCount), inline: true },
        { name: "rejected", value: String(rejectedCount), inline: true },
        {
          name: "mode",
          value: (consensus.min_votes ?? 1) <= 1 ? "single" : `min≥${consensus.min_votes}`,
          inline: true,
        },
      ],
    });
  }
  if (submit) {
    if (submit.skipped || submit.error) {
      const reason = submit.error || submit.reason || "skipped";
      notifyDiscordFireAndForget({
        title: `Submit · skipped · ${bucket}`,
        body: [
          reason,
          reason === "hold" ? "(paired: empty proposal / hold)" : null,
          reason === "no_consensus" ? "(paired: no_consensus above)" : null,
        ]
          .filter(Boolean)
          .join("\n"),
        kind: reason === "hold" || reason === "no_consensus" ? "consensus" : "issue",
        ok: reason === "hold",
      });
    } else {
      notifyDiscordFireAndForget({
        title: submit.dry_run ? `Submit · dry-run · ${bucket}` : `Submit · paper · ${bucket}`,
        body: [
          summarizeOrders(
            Array.isArray(submit.orders)
              ? submit.orders.map((r) => {
                  const row = r as { order?: Record<string, unknown> };
                  return row.order || r;
                })
              : consensus?.orders,
          ),
          submit.note || null,
        ]
          .filter(Boolean)
          .join("\n"),
        kind: "submit",
        ok: !submit.dry_run,
      });
    }
  }
  if (dayEnd) {
    notifyDiscordFireAndForget({
      title: `Day-end · ${bucket.slice(0, 10)}`,
      body: dayEnd.error
        ? `error: ${dayEnd.error}`
        : JSON.stringify(dayEnd.stats || dayEnd).slice(0, 500),
      kind: "day_end",
      ok: !dayEnd.error,
    });
  }

  const lines = [
    err ? `error: ${err}` : "ok",
    fanout?.mode ? `fanout=${fanout.mode}` : null,
    consensus
      ? `proposal=${!(consensus.orders || []).length ? "hold" : `${(consensus.orders || []).length} order(s)`}`
      : null,
    submit
      ? `submit=${submit.skipped ? submit.reason : submit.dry_run ? "dry-run" : "live"}`
      : null,
  ].filter(Boolean);
  notifyDiscordFireAndForget({
    title: `Tick end · ${bucket}`,
    body: lines.join(" · "),
    kind: err ? "issue" : "tick_end",
    ok: !err,
  });
}

export function runDayEndAnalysis(day: string): Record<string, unknown> {
  const py = process.env.DAYTRADE_PYTHON || "python3";
  const script = path.join(scriptsDir(), "day_end_analysis.py");
  const args =
    py === "py" || py.endsWith("\\py.exe") || py.endsWith("/py")
      ? ["-3", script, "--date", day]
      : [script, "--date", day];
  const cmd = py === "py" || py.endsWith("\\py.exe") || py.endsWith("/py") ? "py" : py;
  const r = spawnSync(cmd, args, {
    encoding: "utf8",
    cwd: scriptsDir(),
    env: process.env,
  });
  if (r.status !== 0) {
    return {
      error: r.stderr || r.stdout || `day_end_analysis exit ${r.status}`,
      status: r.status,
    };
  }
  try {
    return JSON.parse(r.stdout || "{}");
  } catch {
    return { raw: r.stdout };
  }
}

export async function runHour(opts: RunOptions): Promise<Record<string, unknown>> {
  loadEnvFile(opts.envFile);
  const phase: Phase = opts.phase || "full";

  if (phase === "day-end") {
    const dayStr = opts.hour.includes("T")
      ? formatDay(parseHourBucket(opts.hour).day)
      : opts.hour;
    notifyDiscordFireAndForget({
      title: `Day-end analysis · ${dayStr}`,
      body: "Building day-end brief for next-session packs…",
      kind: "day_end",
    });
    const result = runDayEndAnalysis(dayStr);
    const stats = (result as { stats?: Record<string, unknown> }).stats;
    const brief =
      typeof (result as { for_next_session?: string }).for_next_session === "string"
        ? String((result as { for_next_session?: string }).for_next_session).slice(0, 500)
        : result.error
          ? `error: ${result.error}`
          : JSON.stringify(stats || result).slice(0, 500);
    notifyDiscordFireAndForget({
      title: `Day-end done · ${dayStr}`,
      body: brief,
      kind: "day_end",
      ok: !result.error,
      fields: stats
        ? Object.entries(stats)
            .slice(0, 6)
            .map(([k, v]) => ({ name: k, value: String(v), inline: true }))
        : undefined,
    });
    writeStatus({ phase: "day-end", day: dayStr, result, finished_at: isoZ() });
    return { day: dayStr, phase: "day-end", ...result, finished_at: isoZ() };
  }

  const { day, hour, minute, slot, asOf } = parseHourBucket(opts.hour);
  const dayStr = formatDay(day);
  const outDir = hourlyDir(dayStr, slot);
  fs.mkdirSync(outDir, { recursive: true });
  const bucket = bucketFor(day, hour, minute);

  notifyDiscordFireAndForget({
    title: `Tick start · ${bucket}`,
    body: `phase=${phase} dry_run=${opts.submit === false}`,
    kind: "tick_start",
    fields: [
      { name: "slot", value: slot, inline: true },
      { name: "as_of", value: asOf, inline: true },
    ],
  });

  const doSubmit = opts.submit !== false;
  const report: Record<string, unknown> = {
    as_of: asOf,
    day: dayStr,
    hour_et: String(hour).padStart(2, "0"),
    minute_et: String(minute).padStart(2, "0"),
    slot,
    phase,
    started_at: isoZ(),
    dry_run: !doSubmit,
    steps: {} as Record<string, unknown>,
  };
  const steps = report.steps as Record<string, unknown>;

  if (!opts.allowNonRth && !isRthConsensusTick(day, hour, minute)) {
    report.error = `${asOf} outside RTH consensus ticks (09:30-15:30 ET half-hours)`;
    writeJson(path.join(outDir, "settle.json"), report);
    notifyDiscordFireAndForget({
      title: `Tick skipped · ${bucket}`,
      body: String(report.error),
      kind: "issue",
      ok: false,
    });
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
        notifyTickOutcome(bucket, report);
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

    const packs = buildHourlyPacks(dayStr, slot);
    steps.packs = { wrote: packs };

    const ready = {
      as_of: asOf,
      day: dayStr,
      slot,
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
      notifyTickOutcome(bucket, report);
      return report;
    }
  }

  if (doFanout) {
    const waitMin = resolveProposalWaitMinutes(opts.proposalWaitMinutes);
    if (opts.fromFixtures) {
      steps.fanout = await fanoutLocalSdk(dayStr, slot, { fromFixtures: true });
    } else if (phase === "fanout" || phase === "full" || phase === "prep-then-settle") {
      steps.fanout = await fanoutLocalSdk(dayStr, slot, {
        fromFixtures: false,
        timeoutMs: Math.max(60_000, waitMin * 60_000),
      });
    }

    if (phase === "fanout") {
      report.finished_at = isoZ();
      writeJson(path.join(outDir, "settle.json"), report);
      notifyTickOutcome(bucket, report);
      return report;
    }
  }

  if (doSettle) {
    if (!proposalsReady(dayStr, slot)) {
      if (opts.fromFixtures) {
        await fanoutLocalSdk(dayStr, slot, { fromFixtures: true });
      } else {
        steps.settle = { skipped: true, reason: "proposals_missing" };
        report.error = "proposals_missing";
        report.finished_at = isoZ();
        writeJson(path.join(outDir, "settle.json"), report);
        writeStatus({
          bucket,
          slot,
          settle_skipped: "proposals_missing",
          finished_at: isoZ(),
        });
        notifyTickOutcome(bucket, report);
        return report;
      }
    }

    const { loaded, missing } = loadProposals(dayStr, slot);
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
    const cpath = writeConsensus(dayStr, slot, consensus);
    steps.consensus = {
      wrote: cpath,
      orders: consensus.orders,
      no_consensus: consensus.no_consensus,
      rejected_legs: consensus.rejected_legs,
      proposals_loaded: consensus.proposals_loaded,
      min_votes: consensus.min_votes,
      missing_agents: consensus.missing_agents,
    };

    let prices: Record<string, number> | undefined;
    const pricesPath = path.join(fixturesDir(), "hourly", "prices.json");
    if (fs.existsSync(pricesPath)) prices = readJson(pricesPath);
    const validation = validateBook(consensus, book, prices);
    steps.validate = validation;

    if (!validation.ok) {
      steps.submit = { skipped: true, reason: "validation_failed" };
    } else if (!consensus.orders.length) {
      // Single-agent hold (empty orders) is valid — nothing to submit
      steps.submit = { skipped: true, reason: "hold" };
    } else {
      const results = await submitConsensusOrders(consensus.orders, {
        dryRun: !doSubmit,
      });
      steps.submit = {
        dry_run: !doSubmit,
        orders: results,
        note: doSubmit
          ? "submitted to Alpaca paper"
          : "dry-run only; omit --dry-run to place Alpaca paper market orders",
      };
      if (doSubmit && credentialsPresent()) {
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

  // After last RTH tick (15:30), write day-end analysis for next session packs.
  if (
    (phase === "settle" || phase === "full" || phase === "prep-then-settle") &&
    hour === 15 &&
    minute === 30
  ) {
    try {
      steps.day_end = runDayEndAnalysis(dayStr);
    } catch (e) {
      steps.day_end = { error: e instanceof Error ? e.message : String(e) };
    }
  }

  report.finished_at = isoZ();
  writeJson(path.join(outDir, "settle.json"), report);
  writeStatus({
    bucket,
    slot,
    as_of: asOf,
    phase,
    finished_at: report.finished_at,
  });
  notifyTickOutcome(bucket, report);
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
  minute: number;
  when: Date;
  bucket: string;
  slot: string;
} {
  const { day: etDay, hour: etHour, minute } = nowEtParts();
  // If we're already past the exact tick start, ask for next at-or-after now+1s
  // by using current minute (nextRthTickFrom keeps tickMins >= nowMins).
  return nextRthTickFrom(etDay, etHour, minute);
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

function currentOrRecentTick(
  day: Date,
  hour: number,
  minute: number,
): { hour: number; minute: number } | null {
  if (!isTradingDay(day)) return null;
  const nowMins = hour * 60 + minute;
  let best: { hour: number; minute: number } | null = null;
  for (const t of RTH_TICKS) {
    const tickMins = t.hour * 60 + t.minute;
    if (tickMins <= nowMins && nowMins < tickMins + 25) {
      best = t;
    }
  }
  return best;
}

export async function runLoop(opts: {
  phase?: Phase;
  submit?: boolean;
  catchUp?: boolean;
  proposalWaitMinutes?: number;
  envFile?: string;
}): Promise<void> {
  loadEnvFile(opts.envFile);
  console.log("[orchestrator] loop started (30m RTH ticks; Ctrl+C to stop)");
  if (opts.catchUp) {
    const { day, hour, minute } = nowEtParts();
    const tick = currentOrRecentTick(day, hour, minute);
    if (tick) {
      console.log(`[orchestrator] catch-up tick ${tick.hour}:${String(tick.minute).padStart(2, "0")}`);
      await runHour({
        hour: bucketFor(day, tick.hour, tick.minute),
        phase: opts.phase || "prep-then-settle",
        submit: opts.submit,
        proposalWaitMinutes: resolveProposalWaitMinutes(opts.proposalWaitMinutes),
        envFile: opts.envFile,
      });
    }
  }
  while (true) {
    const next = nextRthTickClean();
    // If catch-up just ran this exact tick, advance past it
    writeStatus({
      next_tick: next.when.toISOString(),
      bucket: next.bucket,
      slot: next.slot,
      mode: "loop",
      cadence: "30m",
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
        proposalWaitMinutes: resolveProposalWaitMinutes(opts.proposalWaitMinutes),
        envFile: opts.envFile,
      });
      console.log(JSON.stringify({ finished: report.finished_at, error: report.error }, null, 2));
    } catch (e) {
      console.error("[orchestrator] tick error:", e);
      writeStatus({ error: String(e), at: isoZ() });
      notifyDiscordFireAndForget({
        title: `Issue · loop · ${next.bucket}`,
        body: e instanceof Error ? e.message : String(e),
        kind: "issue",
        ok: false,
      });
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
}
