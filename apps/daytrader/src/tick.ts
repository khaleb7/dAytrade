import * as fs from "node:fs";
import * as path from "node:path";
import { reconcile, sizingBook, submitOrder } from "./alpaca.js";
import { asOfIso, cutoffUtc, isRthTick, nowEt, slotKey, snapTick } from "./clock.js";
import { notifyDiscord } from "./discord.js";
import { runAgent } from "./fanout.js";
import { buildPrompt } from "./prompt.js";
import { fetchContext } from "./tracker.js";
import type { Bar } from "./types.js";
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

function pricesFrom(bars: Bar[], bookMarks: Record<string, number>): Record<string, number> {
  const px = { ...bookMarks };
  for (const bar of bars) {
    if (bar.close != null && bar.close > 0 && px[bar.symbol] == null) px[bar.symbol] = bar.close;
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
  const cutoff = cutoffUtc(et.day, snapped.hour, snapped.minute).toISOString().replace(".000Z", "Z");
  const slot = slotKey(snapped.hour, snapped.minute);
  console.log(`[daytrader] tick ${asOf} slot=${slot}`);

  fs.mkdirSync(env.workDir, { recursive: true });
  const context = await fetchContext(env.newstrackerUrl, cutoff);
  const rawBook = await reconcile();
  const book = sizingBook(rawBook);
  const prompt = buildPrompt({
    promptsDir: env.promptsDir,
    asOf,
    cutoffUtc: cutoff,
    book,
    context,
    workDir: env.workDir,
  });
  fs.writeFileSync(path.join(env.workDir, "prompt.md"), prompt);
  const proposal = await runAgent({
    workDir: env.workDir,
    prompt,
    asOf,
    modelId: env.modelId,
    timeoutMs: env.timeoutMs,
  });
  const marks: Record<string, number> = {};
  for (const p of book.positions) {
    if (p.mark_price > 0) marks[p.symbol] = p.mark_price;
  }
  const verdict = validateOrders(proposal.orders, book, pricesFrom(context.bars, marks));
  if (!verdict.ok) {
    console.log(`[daytrader] reject ${verdict.errors.join("; ")}`);
    await notifyDiscord(`Daytrader ${slot} rejected`, verdict.errors.join("\n"), false);
    return 0;
  }
  if (verdict.hold || proposal.orders.length === 0) {
    console.log(`[daytrader] hold ${proposal.thesis}`);
    await notifyDiscord(`Daytrader ${slot} hold`, proposal.thesis || "no orders", true);
    return 0;
  }
  if (env.dryRun) {
    console.log(`[daytrader] dry-run ${proposal.orders.length} orders`);
    await notifyDiscord(`Daytrader ${slot} dry-run`, JSON.stringify(proposal.orders), true);
    return 0;
  }
  let failed = 0;
  for (const order of proposal.orders) {
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
    `${proposal.orders.length - failed} ok, ${failed} failed`,
    failed === 0,
  );
  return failed === 0 ? 0 : 1;
}
