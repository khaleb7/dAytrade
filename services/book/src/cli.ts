#!/usr/bin/env node
import fs from "node:fs";
import {
  bookPortfolioPath,
  readJson,
  type BookPortfolio,
} from "@daytrade/shared";
import { credentialsPresent, getAccount, reconcile, sizingBook } from "./index.js";

async function main(): Promise<void> {
  const cmd = process.argv[2] || "sizing";

  if (cmd === "sizing") {
    let book: BookPortfolio = {
      cash_usd: 100000,
      equity_usd: 100000,
      positions: [],
    };
    if (fs.existsSync(bookPortfolioPath()) && !process.argv.includes("--demo-100k")) {
      book = readJson(bookPortfolioPath());
    }
    const sized = sizingBook(book);
    console.log(
      JSON.stringify(
        {
          broker_equity_usd: sized.broker_equity_usd ?? book.equity_usd,
          sizing_equity_usd: sized.equity_usd,
          equity_offset_usd: sized.equity_offset_usd,
          cash_usd: sized.cash_usd,
        },
        null,
        2,
      ),
    );
    return;
  }

  if (!credentialsPresent()) {
    console.error("APCA_API_KEY_ID / APCA_API_SECRET_KEY not set");
    process.exit(1);
  }
  if (cmd === "account") {
    const acct = await getAccount();
    console.log(
      JSON.stringify(
        {
          id: acct.id,
          status: acct.status,
          equity: acct.equity,
          cash: acct.cash,
          buying_power: acct.buying_power,
        },
        null,
        2,
      ),
    );
    return;
  }
  if (cmd === "reconcile") {
    const m = await reconcile();
    console.log(
      JSON.stringify(
        {
          equity_usd: m.equity_usd,
          cash_usd: m.cash_usd,
          sizing_equity_usd: m.sizing_equity_usd,
          sizing_cash_usd: m.sizing_cash_usd,
          positions: m.positions.length,
        },
        null,
        2,
      ),
    );
    return;
  }
  console.error("usage: book sizing|account|reconcile [--demo-100k]");
  process.exit(1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
