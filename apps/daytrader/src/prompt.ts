import * as fs from "node:fs";
import * as path from "node:path";
import type { Book, TrackerContext } from "./types.js";

export function buildPrompt(opts: {
  promptsDir: string;
  asOf: string;
  cutoffUtc: string;
  book: Book;
  context: TrackerContext;
  workDir: string;
}): string {
  const system = fs.readFileSync(path.join(opts.promptsDir, "agent_system.md"), "utf8");
  const a1 = fs.readFileSync(path.join(opts.promptsDir, "A1.md"), "utf8");
  const proposalPath = path.join(opts.workDir, "A1.json");
  return `${system}

${a1}

# Hourly input pack — ${opts.asOf}

You propose orders for the shared Alpaca paper book. Valid orders are submitted after cap checks. Empty orders are a hold.

## Meta

- as_of: ${opts.asOf} (tick start, America/New_York)
- agent_id: A1
- Cutoff (UTC): ${opts.cutoffUtc} — use only news with published before this instant
- Shared book caps: cash floor 8%, max name 45%, max 7 positions
- Sizing equity is about $1000 (equity_offset already applied)

## News and latest bars (from Newstracker)

\`\`\`json
${JSON.stringify({ articles: opts.context.articles, bars: opts.context.bars }, null, 2)}
\`\`\`

Do not invent headlines or prices. Bars are context for marks already observed before the cutoff.

## Shared book (sizing view)

\`\`\`json
${JSON.stringify(opts.book, null, 2)}
\`\`\`

## Task

Write raw JSON to \`${proposalPath}\` and do not wrap it in markdown. Shape:

\`\`\`json
{
  "agent_id": "A1",
  "as_of": "${opts.asOf}",
  "orders": [],
  "thesis": "…"
}
\`\`\`

Buys: {"side":"buy","symbol":"VTI","notional_usd":50.0}
Sells close or reduce a long: {"side":"sell","symbol":"AAPL","qty":0.15}
No shorts. No options, crypto, OTC, or VIX products.
`;
}
