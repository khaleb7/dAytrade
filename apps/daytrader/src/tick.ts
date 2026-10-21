import * as fs from "node:fs";
import {
  cancelOrder,
  filledStopSells,
  latestTrades,
  listOpenOrders,
  minuteOpens,
  reconcile,
  sessionSellSymbols,
  sizingBook,
  submitOrder,
  submitStopSell,
  waitForFill,
} from "./alpaca.js";
import { breached, breakerGap, linePrice, loadBreaker, planBreaker, saveBreaker, type BreakerMemory } from "./breaker.js";
import { isTradingDay } from "./calendar.js";
import { asOfIso, cutoffUtc, isEodSummary, isRthTick, nowEt, previousCutoff, sessionDate, slotKey, snapTick } from "./clock.js";
import { formatAccountSummary, notifyDiscord } from "./discord.js";
import { buildRuleOrders, ruleConfigFromEnv } from "./rules.js";
import {
  applyFreshLast,
  armScalpScoreboard,
  buyThenLimit,
  describePicks,
  flattenPlans,
  loadReserve,
  limitNewNames,
  marketSellExperiment,
  openExitPlans,
  rearmUncovered,
  requotePicks,
  scalpActive,
  heldAddsOnly,
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

/** 16:10 ET. Read the Alpaca account after the close and post it. No orders. */
async function runEodSummary(): Promise<number> {
  try {
    const book = await reconcile();
    const body = formatAccountSummary(book);
    console.log(`[daytrader] eod summary\n${body}`);
    await notifyDiscord("Daytrader close", body, (book.status || "ACTIVE") === "ACTIVE");
    return 0;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error(`[daytrader] eod summary failed: ${message}`);
    await notifyDiscord("Daytrader close", "account read failed", false);
    return 1;
  }
}

/** 15:55 ET flatten, while the regular session is still open. Every scalp still held is sold. */
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
  const plans = flattenPlans(book.positions, reserved);
  const sells: Order[] = plans.map((plan) => ({ side: "sell" as const, symbol: plan.symbol, qty: plan.qty }));
  const notes = plans.map((plan) => `flatten ${plan.symbol}`);
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
      const id = await marketSellExperiment(plan.symbol, plan.qty);
      lines.push(`sold ${plan.symbol} id=${id}`);
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
  const candidates = buysOpen ? requotePicks(selection, quotes, articles) : [];
  let picks = selection.picks;
  let leftBand: string[] = [];
  let requoteFailed = false;
  let stopQuoteFailed = false;
  const quoteSymbols = [
    ...new Set([
      ...(buysOpen ? candidates.map((pick) => pick.symbol) : []),
      ...(entriesOpen ? [...held] : []),
    ]),
  ];
  let freshLast: Record<string, number> = {};
  if (quoteSymbols.length) {
    try {
      freshLast = await latestTrades(quoteSymbols);
      for (const [symbol, px] of Object.entries(freshLast)) marks[symbol] = px;
    } catch (err) {
      stopQuoteFailed = true;
      if (buysOpen && candidates.length) {
        requoteFailed = true;
        picks = [];
      }
      const message = err instanceof Error ? err.message : String(err);
      console.error(`[daytrader] fresh trade failed: ${message}`);
    }
  }
  if (buysOpen && candidates.length && !requoteFailed) {
    let halfHour: Record<string, number> = {};
    try {
      halfHour = await minuteOpens(candidates.map((pick) => pick.symbol), previousCutoff(day, snapped.hour, snapped.minute));
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.error(`[daytrader] half-hour anchor failed: ${message}`);
    }
    const requoted = applyFreshLast(candidates, quotes, freshLast, halfHour);
    picks = limitNewNames(requoted.picks, held, scalpSlots(held.size));
    leftBand = requoted.leftBand.filter((symbol) => !picks.some((pick) => pick.symbol === symbol));
  }
  const stops = entriesOpen && !stopQuoteFailed ? stopPlans(book.positions, reserved, freshLast) : [];
  if (stops.length) {
    const stopped = new Set(stops.map((plan) => plan.symbol.toUpperCase()));
    picks = picks.filter((pick) => !stopped.has(pick.symbol.toUpperCase()));
  }
  const saleBlocksNew = soldToday.size > 0 || reentryCheckFailed || stops.length > 0;
  const clipBlocksNew = snapped.hour >= 13;
  const skippedNew =
    buysOpen && (saleBlocksNew || clipBlocksNew) ? picks.filter((pick) => !held.has(pick.symbol)) : [];
  if (skippedNew.length) picks = heldAddsOnly(picks, held);
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
  const stillExtended = selection.extended.filter((symbol) => !picks.some((pick) => pick.symbol === symbol));
  const reason = !entriesOpen
    ? exits.length
      ? `open exit ${exits.map((plan) => plan.symbol).join(", ")}`
      : "no overnight scalp to sell"
    : buysOpen
      ? picks.length
        ? [
            describePicks(picks, stillExtended, selection.reentry),
            leftBand.length ? `requote left band ${leftBand.join(", ")}` : "",
          ]
            .filter(Boolean)
            .join("; ")
        : leftBand.length
          ? `requote left band ${leftBand.join(", ")}`
          : describePicks(picks, stillExtended, selection.reentry)
      : "no new buys in the last hour before a weekend or holiday";
  const newNameWhy =
    stops.length || soldToday.size > 0
      ? "no new name after a sale"
      : reentryCheckFailed
        ? "no new name; reentry check failed"
        : "13:00 clip does not open";
  const newNameNote = skippedNew.length
    ? `${newNameWhy} ${skippedNew.map((pick) => pick.symbol).join(", ")}`
    : "";
  const noted = [reason, newNameNote, stops.length ? `stop ${stops.map((plan) => plan.symbol).join(", ")}` : ""]
    .filter(Boolean)
    .join("; ");
  console.log(`[daytrader] scalp ${noted} orders=${orders.length}`);
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
      ...(newNameNote ? [newNameNote] : []),
      ...(reentryCheckFailed ? ["reentry check failed"] : []),
      ...(requoteFailed ? ["requote failed"] : []),
      ...(stopQuoteFailed && entriesOpen ? ["stop quote failed"] : []),
    ],
    agent_decision: "scalp",
    agent_reason: noted,
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

function sleeveSymbols(): string[] {
  return ruleConfigFromEnv().targets.map((target) => target.symbol);
}

async function cancelStopSells(symbol: string): Promise<void> {
  const open = await listOpenOrders();
  for (const order of open) {
    if (order.symbol !== symbol.toUpperCase() || order.side !== "sell") continue;
    if (order.type !== "stop" && order.type !== "stop_limit") continue;
    await cancelOrder(order.id);
  }
}

/** Circuit-breaker sells go out before the rebalance. */
async function submitBreakerSells(
  sells: Order[],
  book: Book,
  marks: Record<string, number>,
  slot: string,
  dryRun: boolean,
): Promise<number> {
  if (!sells.length) return 0;
  const verdict = validateOrders(sells, book, marks);
  if (!verdict.ok) {
    console.log(`[daytrader] breaker rejected ${verdict.errors.join("; ")}`);
    await notifyDiscord(`Daytrader ${slot} breaker rejected`, verdict.errors.join("\n"), false);
    return sells.length;
  }
  if (dryRun) {
    console.log(`[daytrader] breaker dry-run ${sells.length}`);
    await notifyDiscord(`Daytrader ${slot} breaker dry-run`, JSON.stringify(sells), true);
    return 0;
  }
  let failed = 0;
  const lines: string[] = [];
  for (const order of sells) {
    if (order.side !== "sell") continue;
    try {
      await cancelStopSells(order.symbol);
      const resp = await submitOrder(order);
      lines.push(`${order.symbol} id=${String(resp.id || "")}`);
      console.log(`[daytrader] breaker sell ${order.symbol} id=${String(resp.id || "")}`);
    } catch (err) {
      failed += 1;
      const message = err instanceof Error ? err.message : String(err);
      lines.push(`${order.symbol} failed: ${message}`);
      console.error(`[daytrader] breaker sell failed ${order.symbol}: ${message}`);
    }
  }
  await notifyDiscord(`Daytrader ${slot} breaker`, lines.join("\n") || "no sell", failed === 0);
  return failed;
}

/** Rest a day stop 7% under the session open. A rejected fractional stop leaves the half-hour sell as the backup. */
async function armCircuitStops(
  positions: Book["positions"],
  quotes: Quote[],
  memory: BreakerMemory,
  gap: number,
): Promise<void> {
  if (!(gap > 0)) return;
  const symbols = new Set(sleeveSymbols());
  let open: Awaited<ReturnType<typeof listOpenOrders>> = [];
  try {
    open = await listOpenOrders();
  } catch (err) {
    console.error(`[daytrader] breaker stops unread: ${err instanceof Error ? err.message : String(err)}`);
    return;
  }
  for (const order of open) {
    if (order.side !== "sell" || (order.type !== "stop" && order.type !== "stop_limit")) continue;
    if (!memory.tripped[order.symbol]) continue;
    try {
      await cancelOrder(order.id);
    } catch (err) {
      console.error(`[daytrader] breaker stop cancel failed ${order.symbol}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  for (const position of positions) {
    const symbol = position.symbol.toUpperCase();
    if (!symbols.has(symbol) || !(position.qty > 0) || memory.tripped[symbol]) continue;
    const quote = quotes.find((item) => item.symbol.toUpperCase() === symbol);
    if (!quote?.session_open || !(quote.session_open > 0) || breached(quote, gap)) continue;
    const line = linePrice(quote.session_open, gap);
    const stops = open.filter(
      (order) =>
        order.symbol === symbol &&
        order.side === "sell" &&
        (order.type === "stop" || order.type === "stop_limit"),
    );
    const match = stops.length === 1 && Math.abs(stops[0].qty - position.qty) < 1e-6 && Math.abs(stops[0].stopPrice - line) < 0.001;
    if (match) continue;
    let cleared = true;
    for (const order of stops) {
      try {
        await cancelOrder(order.id);
      } catch (err) {
        cleared = false;
        console.error(`[daytrader] breaker stop replace failed ${symbol}: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
    if (!cleared) continue;
    try {
      const resp = await submitStopSell(symbol, position.qty, line);
      console.log(`[daytrader] breaker stop ${symbol} ${line.toFixed(2)} id=${String(resp.id || "")}`);
    } catch (err) {
      console.error(`[daytrader] breaker stop rejected ${symbol}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
}

/** One CronJob invocation. Exit 0 when the slot is not an RTH tick. */
export async function runTick(env: TickEnv): Promise<number> {
  const et = nowEt(env.now);
  if (isEodSummary(et.hour, et.minute)) {
    if (!isTradingDay(et.day)) {
      console.log("[daytrader] skip eod summary; not a trading day");
      return 0;
    }
    return runEodSummary();
  }
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
  const gap = breakerGap();
  const symbols = sleeveSymbols();
  let memory = gap > 0 ? loadBreaker() : { seenSession: null, seenPrior: {}, tripped: {} };
  const sessionOpen = cutoffUtc(et.day, 9, 30);
  let filledStops = new Set<string>();
  if (gap > 0) {
    try {
      filledStops = await filledStopSells(sessionOpen);
    } catch (err) {
      console.error(`[daytrader] breaker fills unread: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  let planned = planBreaker({
    sessionDate: session,
    slot,
    gap,
    symbols,
    quotes: context.quotes,
    positions: book.positions,
    orders: rules.orders,
    memory,
    filledStops,
  });
  memory = planned.memory;
  if (gap > 0) saveBreaker(memory);
  const breakerSells = planned.orders.filter(
    (order) => order.side === "sell" && Boolean(memory.tripped[order.symbol.toUpperCase()]),
  );
  let sleeveOrders = planned.orders.filter((order) => !breakerSells.includes(order));
  const sessions = scoredSessions();
  const dryRun = env.dryRun || sessions < minScoredSessions();
  let breakerFailed = await submitBreakerSells(breakerSells, book, marks, slot, dryRun);
  let sleeveBook = book;
  if (breakerSells.length && !dryRun) {
    try {
      sleeveBook = sizingBook(await reconcile());
    } catch (err) {
      console.error(`[daytrader] breaker reread failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  const orders = sleeveOrders;
  const reason = [...rules.notes, ...planned.notes].filter(Boolean).join("; ");
  console.log(
    `[daytrader] orders=${orders.length} breaker=${breakerSells.length} scored_sessions=${sessions} dry=${dryRun}`,
  );

  const verdict = validateOrders(orders, sleeveBook, marks);
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
    orders: [...breakerSells, ...accepted],
    rule_notes: [...rules.notes, ...planned.notes],
    agent_decision: "rule",
    agent_reason: reason,
    dry_run: dryRun || !verdict.ok,
    excess: null,
  });

  const arm = async (): Promise<void> => {
    if (dryRun || !(gap > 0)) return;
    try {
      const held = sizingBook(await reconcile());
      await armCircuitStops(held.positions, context.quotes, memory, gap);
    } catch (err) {
      console.error(`[daytrader] breaker stop arm failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  if (!verdict.ok) {
    await arm();
    return breakerFailed ? 1 : 0;
  }
  if (verdict.hold || accepted.length === 0) {
    console.log(`[daytrader] hold ${reason}`);
    await notifyDiscord(`Daytrader ${slot} hold`, reason || "no orders", true);
    await arm();
    return breakerFailed ? 1 : 0;
  }
  if (dryRun) {
    console.log(`[daytrader] dry-run ${accepted.length} orders`);
    await notifyDiscord(
      `Daytrader ${slot} dry-run`,
      `${reason}\n${JSON.stringify(accepted)}\nscored sessions ${sessions}/${minScoredSessions()}`,
      true,
    );
    return 0;
  }
  let failed = breakerFailed;
  const buyIds: string[] = [];
  for (const order of accepted) {
    try {
      const resp = await submitOrder(order);
      if (order.side === "buy" && resp.id) buyIds.push(String(resp.id));
      console.log(`[daytrader] submitted ${order.side} ${order.symbol} id=${String(resp.id || "")}`);
    } catch (e) {
      failed += 1;
      console.error(`[daytrader] submit failed ${order.symbol}: ${e instanceof Error ? e.message : String(e)}`);
    }
  }
  for (const id of buyIds) {
    try {
      await waitForFill(id);
    } catch (err) {
      console.error(`[daytrader] fill wait failed ${id}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  await arm();
  await notifyDiscord(
    `Daytrader ${slot} submit`,
    `${accepted.length} rebalance, ${breakerSells.length} breaker, ${failed} failed`,
    failed === 0,
  );
  return failed === 0 ? 0 : 1;
}
