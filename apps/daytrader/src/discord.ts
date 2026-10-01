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
