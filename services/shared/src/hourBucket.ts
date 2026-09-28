import { formatDay, isTradingDay, nthWeekdayPython, parseDay } from "./calendar.js";

export function etOffsetHours(d: Date): number {
  const y = d.getUTCFullYear();
  const dstStart = nthWeekdayPython(y, 3, 6, 2); // Sunday
  const dstEnd = nthWeekdayPython(y, 11, 6, 1);
  const key = formatDay(d);
  return key >= formatDay(dstStart) && key < formatDay(dstEnd) ? 4 : 5;
}

export function asOfIso(day: Date, hour: number): string {
  if (hour < 0 || hour > 23) throw new Error(`hour must be 0-23, got ${hour}`);
  const off = etOffsetHours(day);
  const y = day.getUTCFullYear();
  const m = String(day.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(day.getUTCDate()).padStart(2, "0");
  const hh = String(hour).padStart(2, "0");
  return `${y}-${m}-${dd}T${hh}:00:00-${String(off).padStart(2, "0")}:00`;
}

export function cutoffUtc(day: Date, hour: number): Date {
  const off = etOffsetHours(day);
  return new Date(
    Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), hour + off, 0, 0),
  );
}

export function parseHourBucket(
  s: string,
  opts: { utc?: boolean } = {},
): { day: Date; hour: number; asOf: string } {
  let raw = s.trim().replace(" ", "T");
  if (!raw.includes("T")) throw new Error(`hour bucket must include hour, got ${s}`);
  const [datePart, rest0] = raw.split("T", 2);
  let day = parseDay(datePart);
  let body = rest0;
  let offset: string | null = null;
  if (body.endsWith("Z")) {
    body = body.slice(0, -1);
    offset = "+00:00";
  } else if (body.length >= 6 && (body.at(-6) === "+" || body.at(-6) === "-") && body.at(-3) === ":") {
    offset = body.slice(-6);
    body = body.slice(0, -6);
  }
  const hour = parseInt(body.split(":")[0]!, 10);
  if (Number.isNaN(hour) || hour < 0 || hour > 23) throw new Error(`invalid hour in ${s}`);

  if (opts.utc || offset === "+00:00") {
    const utcDt = new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), hour));
    const off = etOffsetHours(day);
    const localMs = utcDt.getTime() - off * 3600000;
    const local = new Date(localMs);
    // interpret as ET wall via fixed offset
    const etDay = new Date(Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate()));
    const etHour = (hour - off + 24) % 24;
    // simpler: UTC hour - offset = ET hour when same calendar day
    let etH = hour - off;
    let etD = new Date(day);
    if (etH < 0) {
      etH += 24;
      etD = new Date(etD.getTime() - 86400000);
    }
    return { day: etD, hour: etH, asOf: asOfIso(etD, etH) };
  }

  return { day, hour, asOf: asOfIso(day, hour) };
}

export function isRthConsensusHour(day: Date, hour: number): boolean {
  return isTradingDay(day) && hour >= 10 && hour <= 15;
}

export function bucketFor(day: Date, hour: number): string {
  return `${formatDay(day)}T${String(hour).padStart(2, "0")}`;
}

export const RTH_HOURS = [10, 11, 12, 13, 14, 15] as const;
