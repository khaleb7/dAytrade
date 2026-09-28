import * as fs from "node:fs";
import * as path from "node:path";
import { sizingBook } from "@daytrade/book";
import {
  AGENT_IDS,
  asOfIso,
  bookPortfolioPath,
  cutoffUtc,
  formatDay,
  hourlyNewsPath,
  hourlyPackPath,
  lessonsPath,
  promptsDir,
  readJson,
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

export function buildHourlyPacks(
  day: string,
  hour: number,
  opts: { newsPath?: string; bookPath?: string } = {},
): string[] {
  const d = new Date(`${day}T00:00:00Z`);
  // parse day as UTC date parts
  const [y, m, dd] = day.split("-").map(Number);
  const dayDate = new Date(Date.UTC(y!, m! - 1, dd!));
  const asOf = asOfIso(dayDate, hour);
  const cutoff = cutoffUtc(dayDate, hour).toISOString().replace(/\.\d{3}Z$/, "Z");

  const npath = opts.newsPath || hourlyNewsPath(day, hour);
  let news: unknown = { as_of: asOf, items: [], mode: "missing" };
  if (fs.existsSync(npath)) news = readJson(npath);

  const bpath = opts.bookPath || bookPortfolioPath();
  let book: BookPortfolio = { cash_usd: 1000, equity_usd: 1000, positions: [] };
  if (fs.existsSync(bpath)) book = readJson<BookPortfolio>(bpath);
  book = sizingBook(book);

  const tmplPath = path.join(promptsDir(), "hourly_input_template.md");
  const tmpl = fs.readFileSync(tmplPath, "utf8");
  const lessons = lessonsExcerpt();
  const written: string[] = [];

  for (const aid of AGENT_IDS) {
    const text = tmpl
      .replaceAll("{{AS_OF}}", asOf)
      .replaceAll("{{AGENT_ID}}", aid)
      .replaceAll("{{CUTOFF_UTC}}", cutoff)
      .replaceAll("{{NEWS_JSON}}", JSON.stringify(news, null, 2))
      .replaceAll("{{BOOK_JSON}}", JSON.stringify(book, null, 2))
      .replaceAll("{{LESSONS_EXCERPT}}", lessons);
    const out = hourlyPackPath(day, hour, aid);
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, text, "utf8");
    written.push(out);
  }
  return written;
}

export { formatDay };
