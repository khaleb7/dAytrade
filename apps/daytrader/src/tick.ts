import * as fs from "node:fs";
import * as path from "node:path";
import { reconcile, sizingBook, submitOrder } from "./alpaca.js";
import { asOfIso, cutoffUtc, isRthTick, nowEt, previousCutoff, sessionDate, slotKey, snapTick } from "./clock.js";
import { notifyDiscord } from "./discord.js";
import { runAgent } from "./fanout.js";
import { buildPrompt } from "./prompt.js";
import { buildRuleOrders, ruleConfigFromEnv } from "./rules.js";
import { minScoredSessions, recordTick, scorePending, scoredSessions } from "./scoreboard.js";
import { fetchContext } from "./tracker.js";
import type { Order, Quote } from "./types.js";
import { validateOrders } from "./validate.js";

export interface TickEnv {
  newstrackerUrl: string;
  workDir: string;
  promptsDir: string;
  modelId: string;
  timeoutMs: number;
  dryRun: boolean;
  now?: Date;
}

function marksFrom(quotes: Quote[], bookMarks: Record<string, number>): Record<string, number> {
  const px = { ...bookMarks };
  for (const quote of quotes) {
    if (quote.last != null && quote.last > 0) px[quote.symbol] = quote.last;
  }
  return px;
}

/** One CronJob invocation. Exit 0 when the slot is not an RTH tick. */
export async function runTick(env: TickEnv): Promise<number> {
  const et = nowEt(env.now);
  const snapped = snapTick(et.hour, et.minute);
  if (!snapped || !isRthTick(et.day, snapped.hour, snapped.minute)) {
    console.log(
      `[daytrader] skip slot hour=${et.hour} minute=${et.minute} trading=${isRthTick(et.day, snapped?.hour ?? -1, snapped?.minute ?? -1)}`,
    );
    return 0;
  }
  const asOf = asOfIso(et.day, snapped.hour, snapped.minute);
  const cutoff = cutoffUtc(et.day, snapped.hour, snapped.minute);
  const cutoffIso = cutoff.toISOString().replace(".000Z", "Z");
  const sinceIso = previousCutoff(et.day, snapped.hour, snapped.minute).toISOString().replace(".000Z", "Z");
  const slot = slotKey(snapped.hour, snapped.minute);
  console.log(`[daytrader] tick ${asOf} slot=${slot}`);

  fs.mkdirSync(env.workDir, { recursive: true });
  const context = await fetchContext(env.newstrackerUrl, cutoffIso, sinceIso);
  const rawBook = await reconcile();
  const book = sizingBook(rawBook);
  const bookMarks: Record<string, number> = {};
  for (const position of book.positions) {
    if (position.mark_price > 0) bookMarks[position.symbol] = position.mark_price;
  }
  const marks = marksFrom(context.quotes, bookMarks);
  const excess = scorePending(marks);
  if (excess != null) console.log(`[daytrader] prior excess ${excess.toFixed(6)}`);

  const rules = buildRuleOrders(book, context.quotes, ruleConfigFromEnv());
  const prompt = buildPrompt({
    promptsDir: env.promptsDir,
    asOf,
    cutoffUtc: cutoffIso,
    sinceUtc: sinceIso,
    book,
    context,
    orders: rules.orders,
    ruleNotes: rules.notes,
    workDir: env.workDir,
  });
  fs.writeFileSync(path.join(env.workDir, "prompt.md"), prompt);

  let agentDecision = "rule";
  let agentReason = rules.notes.join("; ");
  try {
    const verdict = await runAgent({
      workDir: env.workDir,
      prompt,
      asOf,
      modelId: env.modelId,
      timeoutMs: env.timeoutMs,
    });
    if (verdict) {
      agentDecision = verdict.decision;
      if (verdict.thesis) agentReason = verdict.thesis;
    } else {
      console.log("[daytrader] agent returned no verdict; rules stand");
    }
  } catch (err) {
    console.log(
      `[daytrader] agent skipped: ${err instanceof Error ? err.message : String(err)}; rules stand`,
    );
  }
  const orders: Order[] = agentDecision === "reject" ? [] : rules.orders;
  const sessions = scoredSessions();
  const dryRun = env.dryRun || sessions < minScoredSessions();
  console.log(
    `[daytrader] decision=${agentDecision} orders=${orders.length} scored_sessions=${sessions} dry=${dryRun}`,
  );

  const verdict = validateOrders(orders, book, marks);
  const accepted = verdict.ok ? (verdict.hold ? [] : orders) : [];
  if (!verdict.ok) {
    console.log(`[daytrader] reject ${verdict.errors.join("; ")}`);
    await notifyDiscord(`Daytrader ${slot} rejected`, verdict.errors.join("\n"), false);
  }

  recordTick({
    as_of: cutoffIso,
    slot,
    session_date: sessionDate(et.day),
    entry_equity: book.equity_usd,
    cash: book.cash_usd,
    positions: book.positions.filter((p) => p.qty > 0).map((p) => ({ symbol: p.symbol, qty: p.qty })),
    marks,
    orders: accepted,
    rule_notes: rules.notes,
    agent_decision: agentDecision,
    agent_reason: agentReason,
    dry_run: dryRun || !verdict.ok,
    excess: null,
  });

  if (!verdict.ok) return 0;
  if (verdict.hold || accepted.length === 0) {
    console.log(`[daytrader] hold ${agentReason}`);
    await notifyDiscord(`Daytrader ${slot} hold`, agentReason || "no orders", true);
    return 0;
  }
  if (dryRun) {
    console.log(`[daytrader] dry-run ${accepted.length} orders`);
    await notifyDiscord(
      `Daytrader ${slot} dry-run`,
      `${agentReason}\n${JSON.stringify(accepted)}\nscored sessions ${sessions}/${minScoredSessions()}`,
      true,
    );
    return 0;
  }
  let failed = 0;
  for (const order of accepted) {
    try {
      const resp = await submitOrder(order);
      console.log(`[daytrader] submitted ${order.side} ${order.symbol} id=${String(resp.id || "")}`);
    } catch (e) {
      failed += 1;
      console.error(`[daytrader] submit failed ${order.symbol}: ${e instanceof Error ? e.message : String(e)}`);
    }
  }
  await notifyDiscord(
    `Daytrader ${slot} submit`,
    `${accepted.length - failed} ok, ${failed} failed`,
    failed === 0,
  );
  return failed === 0 ? 0 : 1;
}
