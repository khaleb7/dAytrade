#!/usr/bin/env node
import { buildHour, ingestLiveFeeds } from "./index.js";

async function main(): Promise<void> {
  const cmd = process.argv[2];
  if (cmd === "ingest") {
    console.log(JSON.stringify(await ingestLiveFeeds(), null, 2));
    return;
  }
  if (cmd === "build-hour") {
    const bucket = process.argv[3];
    if (!bucket) throw new Error("usage: news-bridge build-hour YYYY-MM-DDTHH");
    console.log(JSON.stringify(await buildHour(bucket, { skipIngest: true }), null, 2));
    return;
  }
  console.error("usage: news-bridge ingest|build-hour BUCKET");
  process.exit(1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
