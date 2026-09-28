#!/usr/bin/env node
import { formatDay, parseHourBucket } from "@daytrade/shared";
import { buildHourlyPacks } from "./index.js";

const bucket = process.argv[2];
if (!bucket) {
  console.error("usage: packs YYYY-MM-DDTHH");
  process.exit(1);
}
const { day, hour } = parseHourBucket(bucket);
const wrote = buildHourlyPacks(formatDay(day), hour);
console.log(JSON.stringify({ wrote }, null, 2));
