#!/usr/bin/env node
import { formatDay, parseHourBucket } from "@daytrade/shared";
import { fanoutLocalSdk } from "./index.js";

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  let bucket = args.find((a) => !a.startsWith("-"));
  const fromFixtures = args.includes("--from-fixtures");
  if (!bucket) {
    console.error("usage: fanout YYYY-MM-DDTHH [--from-fixtures]");
    process.exit(1);
  }
  const { day, hour } = parseHourBucket(bucket);
  const result = await fanoutLocalSdk(formatDay(day), hour, { fromFixtures });
  console.log(JSON.stringify(result, null, 2));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
