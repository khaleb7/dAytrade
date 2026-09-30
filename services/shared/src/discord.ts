/**
 * Discord webhook notifier (soft-fail).
 *
 * URL from env only: DAYTRADE_DISCORD_WEBHOOK_URL
 * Never log the full webhook URL. Missing/errors never throw to callers.
 */

export const DISCORD_WEBHOOK_ENV = "DAYTRADE_DISCORD_WEBHOOK_URL";

export type DiscordNotifyKind =
  | "tick_start"
  | "tick_end"
  | "issue"
  | "consensus"
  | "submit"
  | "day_end"
  | "info";

function webhookUrl(): string | null {
  const raw = (process.env[DISCORD_WEBHOOK_ENV] || "").trim();
  if (!raw) return null;
  if (!/^https:\/\/discord(?:app)?\.com\/api\/webhooks\//i.test(raw)) {
    console.warn("[discord] ignoring invalid DAYTRADE_DISCORD_WEBHOOK_URL shape");
    return null;
  }
  return raw;
}

function colorFor(kind: DiscordNotifyKind, ok?: boolean): number {
  if (kind === "issue" || ok === false) return 0xe74c3c; // red
  if (kind === "submit" && ok) return 0x2ecc71; // green
  if (kind === "day_end") return 0x9b59b6; // purple
  if (kind === "tick_start") return 0x3498db; // blue
  if (kind === "consensus") return 0xf39c12; // orange
  return 0x95a5a6; // gray
}

export async function notifyDiscord(opts: {
  title: string;
  body?: string;
  kind?: DiscordNotifyKind;
  ok?: boolean;
  fields?: { name: string; value: string; inline?: boolean }[];
}): Promise<boolean> {
  const url = webhookUrl();
  if (!url) return false;
  const kind = opts.kind || "info";
  const description = (opts.body || "").slice(0, 1800);
  const embed: Record<string, unknown> = {
    title: opts.title.slice(0, 240),
    description: description || undefined,
    color: colorFor(kind, opts.ok),
    timestamp: new Date().toISOString(),
    footer: { text: "DayTrade RTH" },
  };
  if (opts.fields?.length) {
    embed.fields = opts.fields.slice(0, 8).map((f) => ({
      name: String(f.name).slice(0, 100),
      value: String(f.value).slice(0, 500) || "—",
      inline: Boolean(f.inline),
    }));
  }
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: "DayTrade",
        embeds: [embed],
      }),
    });
    if (!res.ok) {
      console.warn(`[discord] webhook HTTP ${res.status} (soft-fail)`);
      return false;
    }
    return true;
  } catch (e) {
    console.warn(
      `[discord] webhook error (soft-fail): ${e instanceof Error ? e.message : String(e)}`,
    );
    return false;
  }
}

/** Fire-and-forget wrapper so trading never awaits Discord failures. */
export function notifyDiscordFireAndForget(
  opts: Parameters<typeof notifyDiscord>[0],
): void {
  void notifyDiscord(opts).catch(() => {
    /* already soft-failed inside */
  });
}

export function discordConfigured(): boolean {
  return Boolean(webhookUrl());
}
