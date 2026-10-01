import * as fs from "node:fs";
import * as path from "node:path";
import type { Book, Order, TrackerContext } from "./types.js";

export function buildPrompt(opts: {
  promptsDir: string;
  asOf: string;
  cutoffUtc: string;
  sinceUtc: string;
  book: Book;
  context: TrackerContext;
  orders: Order[];
  ruleNotes: string[];
  workDir: string;
}): string {
  const system = fs.readFileSync(path.join(opts.promptsDir, "agent_system.md"), "utf8");
  const a1 = fs.readFileSync(path.join(opts.promptsDir, "A1.md"), "utf8");
  const proposalPath = path.join(opts.workDir, "A1.json");
  return `${system}

${a1}

# Tick pack — ${opts.asOf}

The rule batch below is the only order set. Accept it, or reject it and hold. Do not add symbols.

## Meta

- as_of: ${opts.asOf} (tick start, America/New_York)
- agent_id: A1
- Cutoff (UTC): ${opts.cutoffUtc}
- News window starts (UTC): ${opts.sinceUtc} — headlines in this pack were published after the previous tick and before the cutoff
- Shared book caps: cash floor 8%, max name 45%, max 7 positions
- Sizing equity is about $1000 (equity_offset already applied)

## Rule batch

${opts.ruleNotes.join("\n") || "hold"}

\`\`\`json
${JSON.stringify(opts.orders, null, 2)}
\`\`\`

## New wire and session quotes

\`\`\`json
${JSON.stringify({ articles: opts.context.articles, quotes: opts.context.quotes }, null, 2)}
\`\`\`

Do not invent headlines or prices. \`last\` is the latest trade before the cutoff. \`prior_close\` is the previous session's close.

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
  "decision": "accept",
  "reason": "…"
}
\`\`\`

\`decision\` is \`accept\` or \`reject\`.
`;
}
