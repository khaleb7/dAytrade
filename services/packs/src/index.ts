import * as fs from "node:fs";
import * as path from "node:path";
import { sizingBook } from "@daytrade/book";
import {
  activeAgentIds,
  asOfIso,
  bookPortfolioPath,
  cutoffUtc,
  formatDay,
  hourlyNewsPath,
  hourlyPackPath,
  hourlySignalsPath,
  lessonsPath,
  normalizeSlot,
  parseSlot,
  previousTradingDayAnalysis,
  promptsDir,
  readJson,
  signalsLatestPath,
  type BookPortfolio,
} from "@daytrade/shared";

function lessonsExcerpt(n = 20): string {
  const p = lessonsPath();
  if (!fs.existsSync(p)) return "(no lessons yet)";
  const lines = fs
    .readFileSync(p, "utf8")
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  return lines.length ? lines.slice(-n).join("\n") : "(no lessons yet)";
}

function dayEndExcerpt(beforeDay: string): string {
  const analysis = previousTradingDayAnalysis(beforeDay);
  if (!analysis) return "(no prior day-end analysis yet)";
  const brief =
    typeof analysis.for_next_session === "string"
      ? analysis.for_next_session
      : JSON.stringify(analysis, null, 2);
  return brief.slice(0, 4000);
}

function marketSignalsBlock(day: string, slot: string): { text: string; vixLine: string } {
  const candidates = [hourlySignalsPath(day, slot), signalsLatestPath()];
  for (const p of candidates) {
    if (!fs.existsSync(p)) continue;
    try {
      const data = readJson<{
        compact?: string;
        signals?: Record<string, { level?: number | null; change?: number | null; change_pct?: number | null; as_of?: string | null; ok?: boolean }>;
      }>(p);
      const compact =
        typeof data.compact === "string" && data.compact.trim()
          ? data.compact
          : "(market signals present but compact text missing)";
      const vix = data.signals?.vix;
      let vixLine = "VIX: unavailable";
      if (vix?.ok && vix.level != null) {
        const ch =
          vix.change != null
            ? ` Δ ${vix.change >= 0 ? "+" : ""}${vix.change.toFixed(2)}` +
              (vix.change_pct != null
                ? ` / ${vix.change_pct >= 0 ? "+" : ""}${vix.change_pct.toFixed(2)}%`
                : "")
            : "";
        vixLine = `VIX: ${Number(vix.level).toFixed(2)}${ch} as_of=${vix.as_of || "?"}`;
      }
      return { text: compact, vixLine };
    } catch {
      /* try next */
    }
  }
  return {
    text: "(no market signals cached yet — treat as unknown; do not invent levels)",
    vixLine: "VIX: unavailable",
  };
}

export function buildHourlyPacks(
  day: string,
  hourOrSlot: number | string,
  opts: { newsPath?: string; bookPath?: string } = {},
): string[] {
  const slot = normalizeSlot(hourOrSlot);
  const { hour, minute } = parseSlot(slot);
  const [y, m, dd] = day.split("-").map(Number);
  const dayDate = new Date(Date.UTC(y!, m! - 1, dd!));
  const asOf = asOfIso(dayDate, hour, minute);
  const cutoff = cutoffUtc(dayDate, hour, minute).toISOString().replace(/\.\d{3}Z$/, "Z");

  const npath = opts.newsPath || hourlyNewsPath(day, slot);
  let news: unknown = { as_of: asOf, items: [], mode: "missing" };
  if (fs.existsSync(npath)) news = readJson(npath);

  const bpath = opts.bookPath || bookPortfolioPath();
  let book: BookPortfolio = { cash_usd: 1000, equity_usd: 1000, positions: [] };
  if (fs.existsSync(bpath)) book = readJson<BookPortfolio>(bpath);
  book = sizingBook(book);

  const tmplPath = path.join(promptsDir(), "hourly_input_template.md");
  const tmpl = fs.readFileSync(tmplPath, "utf8");
  const lessons = lessonsExcerpt();
  const dayEnd = dayEndExcerpt(day);
  const { text: signals, vixLine } = marketSignalsBlock(day, slot);
  const written: string[] = [];

  for (const aid of activeAgentIds()) {
    const text = tmpl
      .replaceAll("{{AS_OF}}", asOf)
      .replaceAll("{{AGENT_ID}}", aid)
      .replaceAll("{{CUTOFF_UTC}}", cutoff)
      .replaceAll("{{NEWS_JSON}}", JSON.stringify(news, null, 2))
      .replaceAll("{{BOOK_JSON}}", JSON.stringify(book, null, 2))
      .replaceAll("{{LESSONS_EXCERPT}}", lessons)
      .replaceAll("{{DAY_END_ANALYSIS}}", dayEnd)
      .replaceAll("{{MARKET_SIGNALS}}", signals)
      .replaceAll("{{VIX}}", vixLine);
    const out = hourlyPackPath(day, slot, aid);
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, text, "utf8");
    written.push(out);
  }
  return written;
}

export { formatDay };
