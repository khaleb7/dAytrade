import { formatDay, isTradingDay } from "./calendar.js";

/** Half-hour RTH ticks: 09:30–15:30 America/New_York. */
export const RTH_TICKS: readonly { hour: number; minute: number }[] = [
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
];

function nthWeekday(year: number, month: number, weekday: number, n: number): Date {
  let d = new Date(Date.UTC(year, month - 1, 1));
  while (d.getUTCDay() !== (weekday + 1) % 7) d = new Date(d.getTime() + 86400000);
  return new Date(d.getTime() + (n - 1) * 7 * 86400000);
}

/** EDT = 4, EST = 5. DST: second Sunday in March through first Sunday in November. */
export function etOffsetHours(d: Date): number {
  const y = d.getUTCFullYear();
  const dstStart = nthWeekday(y, 3, 6, 2);
  const dstEnd = nthWeekday(y, 11, 6, 1);
  const key = formatDay(d);
  return key >= formatDay(dstStart) && key < formatDay(dstEnd) ? 4 : 5;
}

export interface EtNow {
  day: Date;
  hour: number;
  minute: number;
}

export function nowEt(now = new Date()): EtNow {
  const off = etOffsetHours(now);
  const et = new Date(now.getTime() - off * 3600000);
  return {
    day: new Date(Date.UTC(et.getUTCFullYear(), et.getUTCMonth(), et.getUTCDate())),
    hour: et.getUTCHours(),
    minute: et.getUTCMinutes(),
  };
}

/** Cron fires at :00 and :30; allow a few minutes of scheduler lag. */
export function snapTick(hour: number, minute: number): { hour: number; minute: number } | null {
  if (minute < 5) return { hour, minute: 0 };
  if (minute >= 30 && minute < 35) return { hour, minute: 30 };
  return null;
}

export function isRthTick(day: Date, hour: number, minute: number): boolean {
  if (!isTradingDay(day)) return false;
  return RTH_TICKS.some((t) => t.hour === hour && t.minute === minute);
}

export function asOfIso(day: Date, hour: number, minute: number): string {
  const off = etOffsetHours(day);
  const y = day.getUTCFullYear();
  const m = String(day.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(day.getUTCDate()).padStart(2, "0");
  const hh = String(hour).padStart(2, "0");
  const mm = String(minute).padStart(2, "0");
  return `${y}-${m}-${dd}T${hh}:${mm}:00-${String(off).padStart(2, "0")}:00`;
}

export function cutoffUtc(day: Date, hour: number, minute: number): Date {
  const off = etOffsetHours(day);
  return new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), hour + off, minute, 0));
}

export function slotKey(hour: number, minute: number): string {
  return `${String(hour).padStart(2, "0")}${String(minute).padStart(2, "0")}`;
}

/** Cutoff of the previous RTH tick. 09:30 looks back to the prior session's 15:30. */
export function previousCutoff(day: Date, hour: number, minute: number): Date {
  if (hour === 9 && minute === 30) {
    let d = new Date(day.getTime() - 86400000);
    while (!isTradingDay(d)) d = new Date(d.getTime() - 86400000);
    return cutoffUtc(d, 15, 30);
  }
  if (minute >= 30) return cutoffUtc(day, hour, 0);
  return cutoffUtc(day, hour - 1, 30);
}

export function sessionDate(day: Date): string {
  return day.toISOString().slice(0, 10);
}
