import { formatDay, isTradingDay, nextTradingDay, nthWeekdayPython, parseDay } from "./calendar.js";

/** One RTH consensus tick (America/New_York wall clock). */
export type RthTick = { hour: number; minute: number };

/** Half-hour RTH ticks: 09:30–15:30 ET (market closes 16:00). */
export const RTH_TICKS: readonly RthTick[] = [
  { hour: 9, minute: 30 },
  { hour: 10, minute: 0 },
  { hour: 10, minute: 30 },
  { hour: 11, minute: 0 },
  { hour: 11, minute: 30 },
  { hour: 12, minute: 0 },
  { hour: 12, minute: 30 },
  { hour: 13, minute: 0 },
  { hour: 13, minute: 30 },
  { hour: 14, minute: 0 },
  { hour: 14, minute: 30 },
  { hour: 15, minute: 0 },
  { hour: 15, minute: 30 },
] as const;

/** @deprecated Prefer RTH_TICKS. Unique hour values that appear in RTH_TICKS. */
export const RTH_HOURS = [9, 10, 11, 12, 13, 14, 15] as const;

export function etOffsetHours(d: Date): number {
  const y = d.getUTCFullYear();
  const dstStart = nthWeekdayPython(y, 3, 6, 2); // Sunday
  const dstEnd = nthWeekdayPython(y, 11, 6, 1);
  const key = formatDay(d);
  return key >= formatDay(dstStart) && key < formatDay(dstEnd) ? 4 : 5;
}

/** Directory / identity key: HHMM (e.g. 0930, 1400, 1530). */
export function slotKey(hour: number, minute = 0): string {
  if (hour < 0 || hour > 23) throw new Error(`hour must be 0-23, got ${hour}`);
  if (minute < 0 || minute > 59) throw new Error(`minute must be 0-59, got ${minute}`);
  return `${String(hour).padStart(2, "0")}${String(minute).padStart(2, "0")}`;
}

/** Normalize hour number, "14", "1400", "14:30", or "14-30" → HHMM slot. */
export function normalizeSlot(hourOrSlot: number | string, minute = 0): string {
  if (typeof hourOrSlot === "number") return slotKey(hourOrSlot, minute);
  const raw = String(hourOrSlot).trim();
  if (/^\d{4}$/.test(raw)) return raw;
  if (/^\d{1,2}$/.test(raw)) return slotKey(parseInt(raw, 10), minute);
  const m1 = raw.match(/^(\d{1,2})[:\-](\d{2})$/);
  if (m1) return slotKey(parseInt(m1[1]!, 10), parseInt(m1[2]!, 10));
  throw new Error(`invalid slot ${hourOrSlot}`);
}

export function parseSlot(slot: string): { hour: number; minute: number } {
  const s = normalizeSlot(slot);
  return { hour: parseInt(s.slice(0, 2), 10), minute: parseInt(s.slice(2, 4), 10) };
}

export function asOfIso(day: Date, hour: number, minute = 0): string {
  if (hour < 0 || hour > 23) throw new Error(`hour must be 0-23, got ${hour}`);
  if (minute < 0 || minute > 59) throw new Error(`minute must be 0-59, got ${minute}`);
  const off = etOffsetHours(day);
  const y = day.getUTCFullYear();
  const m = String(day.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(day.getUTCDate()).padStart(2, "0");
  const hh = String(hour).padStart(2, "0");
  const mm = String(minute).padStart(2, "0");
  return `${y}-${m}-${dd}T${hh}:${mm}:00-${String(off).padStart(2, "0")}:00`;
}

export function cutoffUtc(day: Date, hour: number, minute = 0): Date {
  const off = etOffsetHours(day);
  return new Date(
    Date.UTC(
      day.getUTCFullYear(),
      day.getUTCMonth(),
      day.getUTCDate(),
      hour + off,
      minute,
      0,
    ),
  );
}

/** CLI / status bucket: YYYY-MM-DDTHH:MM */
export function bucketFor(day: Date, hour: number, minute = 0): string {
  return `${formatDay(day)}T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

export function isRthConsensusTick(day: Date, hour: number, minute = 0): boolean {
  if (!isTradingDay(day)) return false;
  return RTH_TICKS.some((t) => t.hour === hour && t.minute === minute);
}

/** @deprecated Prefer isRthConsensusTick */
export function isRthConsensusHour(day: Date, hour: number, minute = 0): boolean {
  return isRthConsensusTick(day, hour, minute);
}

export function parseHourBucket(
  s: string,
  opts: { utc?: boolean } = {},
): { day: Date; hour: number; minute: number; slot: string; asOf: string } {
  let raw = s.trim().replace(" ", "T");
  if (!raw.includes("T")) throw new Error(`hour bucket must include hour, got ${s}`);
  const [datePart, rest0] = raw.split("T", 2);
  let day = parseDay(datePart);
  let body = rest0!;
  let offset: string | null = null;
  if (body.endsWith("Z")) {
    body = body.slice(0, -1);
    offset = "+00:00";
  } else if (body.length >= 6 && (body.at(-6) === "+" || body.at(-6) === "-") && body.at(-3) === ":") {
    offset = body.slice(-6);
    body = body.slice(0, -6);
  }

  let hour: number;
  let minute = 0;
  // Compact HHMM (1430) without colons
  if (/^\d{4}$/.test(body)) {
    hour = parseInt(body.slice(0, 2), 10);
    minute = parseInt(body.slice(2, 4), 10);
  } else {
    const parts = body.split(":");
    hour = parseInt(parts[0]!, 10);
    if (parts.length >= 2 && parts[1]) minute = parseInt(parts[1]!, 10);
  }
  if (Number.isNaN(hour) || hour < 0 || hour > 23) throw new Error(`invalid hour in ${s}`);
  if (Number.isNaN(minute) || minute < 0 || minute > 59) throw new Error(`invalid minute in ${s}`);

  if (opts.utc || offset === "+00:00") {
    const utcDt = new Date(
      Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), hour, minute),
    );
    const off = etOffsetHours(day);
    let etH = hour - off;
    let etM = minute;
    let etD = new Date(day);
    if (etH < 0) {
      etH += 24;
      etD = new Date(etD.getTime() - 86400000);
    }
    // Adjust using actual offset conversion
    const localMs = utcDt.getTime() - off * 3600000;
    const local = new Date(localMs);
    etD = new Date(Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate()));
    etH = local.getUTCHours();
    etM = local.getUTCMinutes();
    return {
      day: etD,
      hour: etH,
      minute: etM,
      slot: slotKey(etH, etM),
      asOf: asOfIso(etD, etH, etM),
    };
  }

  return {
    day,
    hour,
    minute,
    slot: slotKey(hour, minute),
    asOf: asOfIso(day, hour, minute),
  };
}

export function tickWhenUtc(day: Date, hour: number, minute: number): Date {
  const off = etOffsetHours(day);
  return new Date(
    Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), hour + off, minute, 0),
  );
}

/** Next RTH half-hour tick at or after "now" (skips ticks already started). */
export function nextRthTickFrom(
  etDay: Date,
  etHour: number,
  etMinute: number,
): { day: Date; hour: number; minute: number; when: Date; bucket: string; slot: string } {
  let d = new Date(etDay);
  let baseDay = formatDay(etDay);
  let nowMins = etHour * 60 + etMinute;

  for (let n = 0; n < 20; n++) {
    if (isTradingDay(d)) {
      const sameDay = formatDay(d) === baseDay;
      for (const t of RTH_TICKS) {
        const tickMins = t.hour * 60 + t.minute;
        if (sameDay && tickMins < nowMins) continue;
        const when = tickWhenUtc(d, t.hour, t.minute);
        return {
          day: d,
          hour: t.hour,
          minute: t.minute,
          when,
          bucket: bucketFor(d, t.hour, t.minute),
          slot: slotKey(t.hour, t.minute),
        };
      }
    }
    d = nextTradingDay(d);
    baseDay = formatDay(d);
    nowMins = 0;
  }
  throw new Error("could not find next RTH tick");
}

export { nextTradingDay };
