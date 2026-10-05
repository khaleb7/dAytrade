import * as fs from "node:fs";
import * as path from "node:path";
import { reconcile, sessionSellSymbols, sizingBook, submitOrder } from "./alpaca.js";
import { isTradingDay } from "./calendar.js";
import { asOfIso, cutoffUtc, isRthTick, nowEt, previousCutoff, sessionDate, slotKey, snapTick } from "./clock.js";
import { notifyDiscord } from "./discord.js";
import { runAgent } from "./fanout.js";
import { buildPrompt } from "./prompt.js";
import { buildRuleOrders, ruleConfigFromEnv } from "./rules.js";
import {
  armScalpScoreboard,
  buyThenLimit,
  describePicks,
  flattenPlans,
  loadReserve,
  marketSellExperiment,
  openExitPlans,
  rearmUncovered,
  restLimit,
  scalpActive,
  holdAfternoonClip,
  scalpBuyOrders,
  scalpBuysOpen,
  scalpEntriesOpen,
  scalpSlots,
  selectScalpBuys,
  stopPlans,
} from "./scalp.js";
import { minScoredSessions, recordTick, scorePending, scoredSessions } from "./scoreboard.js";
import { fetchContext } from "./tracker.js";
import type { Book, NewsArticle, Order, Quote } from "./types.js";
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

function positionMarks(book: Book, quotes: Quote[]): Record<string, number> {
  const marks: Record<string, number> = {};
  for (const position of book.positions) {
    if (position.mark_price > 0) marks[position.symbol] = position.mark_price;
  }
  return marksFrom(quotes, marks);
}

/** 15:55 ET flatten, while the regular session is still open. Green lots that have not reached +1% are sold. Losers keep a GTC limit 1% above cost. */
async function runScalpClose(env: TickEnv, day: Date, snapped: { hour: number; minute: number }): Promise<number> {
  armScalpScoreboard();
  const slot = slotKey(snapped.hour, snapped.minute);
  const asOf = asOfIso(day, snapped.hour, snapped.minute);
  const cutoffIso = cutoffUtc(day, snapped.hour, snapped.minute).toISOString().replace(".000Z", "Z");
  console.log(`[daytrader] scalp close ${asOf}`);
  const book = sizingBook(await reconcile());
  const reserved = loadReserve(book.positions);
  const marks = positionMarks(book, []);
  const excess = scorePending(marks);
  if (excess != null) console.log(`[daytrader] prior excess ${excess.toFixed(6)}`);
  const plans = flattenPlans(book.positions, reserved, marks);
  const sells: Order[] = plans
    .filter((plan) => plan.marketSell)
    .map((plan) => ({ side: "sell" as const, symbol: plan.symbol, qty: plan.qty }));
  const notes = plans.map((plan) =>
    plan.marketSell ? `flatten ${plan.symbol}` : `hold loser ${plan.symbol} limit ${plan.limit}`,
  );
  const verdict = validateOrders(sells, book, marks);
  const accepted = verdict.ok ? sells : [];
  recordTick({
    as_of: cutoffIso,
    slot,
    session_date: sessionDate(day),
    entry_equity: book.equity_usd,
    cash: book.cash_usd,
    positions: book.positions.filter((p) => p.qty > 0).map((p) => ({ symbol: p.symbol, qty: p.qty })),
    marks,
    orders: accepted,
    rule_notes: notes.length ? notes : ["nothing to flatten"],
    agent_decision: "scalp",
    agent_reason: notes.join("; ") || "nothing to flatten",
    dry_run: env.dryRun || !verdict.ok,
    excess: null,
  });
  if (!verdict.ok) {
    console.log(`[daytrader] scalp close rejected ${verdict.errors.join("; ")}`);
    await notifyDiscord(`Daytrader ${slot} scalp rejected`, verdict.errors.join("\n"), false);
    return 0;
  }
  if (env.dryRun) {
    await notifyDiscord(`Daytrader ${slot} scalp dry-run`, notes.join("\n") || "nothing to flatten", true);
    return 0;
  }
  const lines: string[] = [];
  let failed = 0;
  for (const plan of plans) {
    try {
      if (plan.marketSell) {
        const id = await marketSellExperiment(plan.symbol, plan.qty);
        lines.push(`sold ${plan.symbol} id=${id}`);
      } else {
        try {
          const id = await restLimit(plan.symbol, plan.qty, plan.limit, "gtc");
          lines.push(`gtc ${plan.symbol} @ ${plan.limit} id=${id}`);
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          console.error(`[daytrader] gtc failed ${plan.symbol}: ${message}`);
          const id = await restLimit(plan.symbol, plan.qty, plan.limit, "day");
          lines.push(`gtc ${plan.symbol} failed; day limit ${plan.limit} id=${id}`);
        }
      }
    } catch (err) {
      failed += 1;
      const message = err instanceof Error ? err.message : String(err);
      lines.push(`${plan.symbol} failed: ${message}`);
      console.error(`[daytrader] flatten failed ${plan.symbol}: ${message}`);
    }
  }
  if (!lines.length) lines.push("nothing to flatten");
  await notifyDiscord(`Daytrader ${slot} scalp close`, lines.join("\n"), failed === 0);
  return failed === 0 ? 0 : 1;
}

/** Half-hour scalp. Buys names that are up, then rests a day limit 1% above the fill. */
async function runScalpSession(
  env: TickEnv,
  day: Date,
  snapped: { hour: number; minute: number },
  book: Book,
  quotes: Quote[],
  articles: NewsArticle[],
  marks: Record<string, number>,
  cutoffIso: string,
): Promise<number> {
  const slot = slotKey(snapped.hour, snapped.minute);
  const reserved = loadReserve(book.positions);
  const held = new Set(book.positions.filter((p) => p.qty > 0).map((p) => p.symbol.toUpperCase()));
  const entriesOpen = scalpEntriesOpen(snapped.hour, snapped.minute);
  const buysOpen = scalpBuysOpen(day, snapped.hour, snapped.minute);
  const exits = entriesOpen ? [] : openExitPlans(book.positions, reserved);
  const stops = entriesOpen ? stopPlans(book.positions, reserved, marks) : [];
  let soldToday = new Set<string>();
  let reentryCheckFailed = false;
  if (buysOpen) {
    try {
      soldToday = await sessionSellSymbols(cutoffUtc(day, 0, 0));
    } catch (err) {
      reentryCheckFailed = true;
      const message = err instanceof Error ? err.message : String(err);
      console.error(`[daytrader] reentry check failed: ${message}`);
    }
  }
  const selection = buysOpen
    ? selectScalpBuys(quotes, articles, held, scalpSlots(held.size), soldToday)
    : { picks: [], extended: [], reentry: [] };
  const picks = selection.picks;
  const holdClip = buysOpen && holdAfternoonClip(snapped.hour);
  const heldValue: Record<string, number> = {};
  for (const position of book.positions) {
    if (!(position.qty > 0)) continue;
    const px = marks[position.symbol] ?? position.mark_price;
    const mv = position.market_value > 0 ? position.market_value : position.qty * px;
    if (mv > 0) heldValue[position.symbol.toUpperCase()] = mv;
  }
  const buys = scalpBuyOrders(picks, book.cash_usd, book.equity_usd, holdClip, heldValue);
  const orders: Order[] = [
    ...exits.map((plan) => ({ side: "sell" as const, symbol: plan.symbol, qty: plan.qty })),
    ...stops.map((plan) => ({ side: "sell" as const, symbol: plan.symbol, qty: plan.qty })),
    ...buys,
  ];
  const reason = !entriesOpen
    ? exits.length
      ? `open exit ${exits.map((plan) => plan.symbol).join(", ")}`
      : "no overnight scalp to sell"
    : buysOpen
      ? describePicks(picks, selection.extended, selection.reentry)
      : "no new buys in the last hour before a weekend or holiday";
  console.log(`[daytrader] scalp ${reason} orders=${orders.length}`);
  const verdict = validateOrders(orders, book, marks);
  const accepted = verdict.ok ? (verdict.hold ? [] : orders) : [];
  recordTick({
    as_of: cutoffIso,
    slot,
    session_date: sessionDate(day),
    entry_equity: book.equity_usd,
    cash: book.cash_usd,
    positions: book.positions.filter((p) => p.qty > 0).map((p) => ({ symbol: p.symbol, qty: p.qty })),
    marks,
    orders: accepted,
    rule_notes: [
      reason,
      ...exits.map((plan) => `open exit ${plan.symbol}`),
      ...stops.map((plan) => `stop ${plan.symbol}`),
      ...(holdClip ? ["holding one clip until 13:00"] : []),
      ...(reentryCheckFailed ? ["reentry check failed"] : []),
    ],
    agent_decision: "scalp",
    agent_reason: reason,
    dry_run: env.dryRun || !verdict.ok,
    excess: null,
  });
  if (!verdict.ok) {
    console.log(`[daytrader] scalp rejected ${verdict.errors.join("; ")}`);
    await notifyDiscord(`Daytrader ${slot} scalp rejected`, verdict.errors.join("\n"), false);
    return 0;
  }
  if (env.dryRun) {
    await notifyDiscord(`Daytrader ${slot} scalp dry-run`, `${reason}\n${JSON.stringify(accepted)}`, true);
    return 0;
  }
  const lines: string[] = [];
  let failed = 0;
  if (entriesOpen) {
    try {
      const rearmed = await rearmUncovered(book.positions, reserved);
      lines.push(...rearmed);
    } catch (err) {
      failed += 1;
      const message = err instanceof Error ? err.message : String(err);
      lines.push(`rearm failed: ${message}`);
      console.error(`[daytrader] rearm failed: ${message}`);
    }
  }
  for (const order of accepted) {
    try {
      if (order.side === "sell") {
        const id = await marketSellExperiment(order.symbol, order.qty);
        lines.push(`${entriesOpen ? "stop" : "open exit"} ${order.symbol} id=${id}`);
      } else {
        lines.push(await buyThenLimit(order));
      }
    } catch (err) {
      failed += 1;
      const message = err instanceof Error ? err.message : String(err);
      lines.push(`${order.symbol} failed: ${message}`);
      console.error(`[daytrader] scalp buy failed ${order.symbol}: ${message}`);
    }
  }
  if (!lines.length) lines.push(reason);
  await notifyDiscord(`Daytrader ${slot} scalp`, lines.join("\n"), failed === 0);
  return failed === 0 ? 0 : 1;
}

/** One CronJob invocation. Exit 0 when the slot is not an RTH tick. */
export async function runTick(env: TickEnv): Promise<number> {
  const et = nowEt(env.now);
  const snapped = snapTick(et.hour, et.minute);
  const session = sessionDate(et.day);
  if (
    scalpActive(session) &&
    snapped &&
    snapped.hour === 15 &&
    snapped.minute === 55 &&
    isTradingDay(et.day)
  ) {
    return runScalpClose(env, et.day, snapped);
  }
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
  if (scalpActive(session)) armScalpScoreboard();
  const excess = scorePending(marks);
  if (excess != null) console.log(`[daytrader] prior excess ${excess.toFixed(6)}`);
  if (scalpActive(session)) {
    return runScalpSession(env, et.day, snapped, book, context.quotes, context.articles, marks, cutoffIso);
  }

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
