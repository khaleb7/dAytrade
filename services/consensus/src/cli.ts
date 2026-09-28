#!/usr/bin/env node
import * as path from "node:path";
import {
  bookPortfolioPath,
  fixturesDir,
  parseHourBucket,
  formatDay,
  readJson,
  type BookPortfolio,
} from "@daytrade/shared";
import { buildConsensus, loadProposals, writeConsensus } from "./index.js";

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  let bucket = "2026-09-25T14";
  let proposalsDir: string | undefined;
  let i = 0;
  while (i < args.length) {
    if (args[i] === "--bucket" && args[i + 1]) {
      bucket = args[++i]!;
    } else if (args[i] === "--proposals-dir" && args[i + 1]) {
      proposalsDir = args[++i]!;
    } else if (args[i] === "--from-fixtures") {
      proposalsDir = path.join(fixturesDir(), "hourly", "proposals");
    }
    i++;
  }
  const { day, hour, asOf } = parseHourBucket(bucket);
  const dayStr = formatDay(day);
  const { loaded, missing } = loadProposals(dayStr, hour, proposalsDir);
  let held: Record<string, number> = {};
  try {
    const book = readJson<BookPortfolio>(bookPortfolioPath());
    for (const p of book.positions || []) held[p.symbol] = Number(p.qty);
  } catch {
    /* empty */
  }
  const consensus = buildConsensus(loaded, { asOf, heldQty: held });
  if (missing.length) consensus.missing_agents = missing;
  if (!proposalsDir) writeConsensus(dayStr, hour, consensus);
  else {
    const out = path.join(proposalsDir, "..", "consensus.smoke.json");
    const { writeJson } = await import("@daytrade/shared");
    writeJson(out, consensus);
  }
  console.log(JSON.stringify(consensus, null, 2));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
