import type { Book } from "./types.js";

function money(n: number): string {
  return `$${n.toFixed(2)}`;
}

function signedMoney(n: number): string {
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toFixed(2)}`;
}

function qtyLabel(qty: number): string {
  const fixed = qty.toFixed(8);
  return fixed.includes(".") ? fixed.replace(/0+$/, "").replace(/\.$/, "") : fixed;
}

/** Broker equity, day change, cash, and open positions. The account id is omitted. */
export function formatAccountSummary(book: Book): string {
  const lines = [book.status || "unknown", `equity ${money(book.equity_usd)}`];
  const last = book.last_equity_usd;
  if (last != null && last > 0) {
    const delta = book.equity_usd - last;
    const pct = (delta / last) * 100;
    const pctSign = pct > 0 ? "+" : "";
    lines.push(`day ${signedMoney(delta)} (${pctSign}${pct.toFixed(2)}%) from ${money(last)}`);
  }
  lines.push(`cash ${money(book.cash_usd)}`);
  const open = book.positions.filter((position) => position.qty !== 0);
  if (!open.length) {
    lines.push("flat");
  } else {
    lines.push("positions");
    for (const position of [...open].sort((a, b) => a.symbol.localeCompare(b.symbol))) {
      lines.push(
        `${position.symbol} ${qtyLabel(position.qty)} @ ${money(position.mark_price)} (${money(position.market_value)})`,
      );
    }
  }
  return lines.join("\n");
}

/** Optional Discord webhook. Missing URL or HTTP errors never fail the tick. */

export async function notifyDiscord(title: string, body: string, ok: boolean): Promise<void> {
  const url = (process.env.DAYTRADE_DISCORD_WEBHOOK_URL || "").trim();
  if (!url) {
    console.log("[discord] webhook unset");
    return;
  }
  if (!/^https:\/\/discord(?:app)?\.com\/api\/webhooks\//i.test(url)) {
    console.warn("[discord] ignoring invalid webhook URL shape");
    return;
  }
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: "Daytrader",
        embeds: [
          {
            title: title.slice(0, 240),
            description: body.slice(0, 1800),
            color: ok ? 0x2ecc71 : 0xe74c3c,
            timestamp: new Date().toISOString(),
          },
        ],
      }),
    });
    if (res.ok) console.log("[discord] ping sent");
    else console.warn(`[discord] webhook HTTP ${res.status} (soft-fail)`);
  } catch (err) {
    const name = err instanceof Error ? err.name : "Error";
    console.warn(`[discord] webhook error (soft-fail): ${name}`);
  }
}
