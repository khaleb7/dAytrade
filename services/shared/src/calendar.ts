/** NYSE trading-day helpers (weekends + common holidays). */

function nthWeekday(year: number, month: number, weekday: number, n: number): Date {
  // month 1-12; weekday Mon=0 … Sun=6
  if (n > 0) {
    let d = new Date(Date.UTC(year, month - 1, 1));
    while (d.getUTCDay() !== (weekday + 1) % 7) {
      d = new Date(d.getTime() + 86400000);
    }
    d = new Date(d.getTime() + (n - 1) * 7 * 86400000);
    return d;
  }
  // last
  let d =
    month === 12
      ? new Date(Date.UTC(year + 1, 0, 0))
      : new Date(Date.UTC(year, month, 0));
  while (d.getUTCDay() !== (weekday + 1) % 7) {
    d = new Date(d.getTime() - 86400000);
  }
  return d;
}

function observed(d: Date): Date {
  const wd = d.getUTCDay();
  if (wd === 6) return new Date(d.getTime() - 86400000);
  if (wd === 0) return new Date(d.getTime() + 86400000);
  return d;
}

function ymd(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function parseDay(s: string): Date {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) throw new Error(`invalid date ${s}`);
  return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
}

export function formatDay(d: Date): string {
  return ymd(d);
}

export function nyseHolidays(year: number): Set<string> {
  const holidays = new Set<string>();
  holidays.add(ymd(observed(new Date(Date.UTC(year, 0, 1)))));
  holidays.add(ymd(nthWeekday(year, 1, 0, 3)));
  holidays.add(ymd(nthWeekday(year, 2, 0, 3)));
  // Easter (Anonymous Gregorian) → Good Friday
  const a = year % 19;
  const b = Math.floor(year / 100);
  const c = year % 100;
  const d = Math.floor(b / 4);
  const e = b % 4;
  const f = Math.floor((b + 8) / 25);
  const g = Math.floor((b - f + 1) / 3);
  const h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4);
  const k = c % 4;
  const l = (32 + 2 * e + 2 * i - h - k) % 7;
  const m = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * m + 114) / 31);
  const day = ((h + l - 7 * m + 114) % 31) + 1;
  const easter = new Date(Date.UTC(year, month - 1, day));
  holidays.add(ymd(new Date(easter.getTime() - 2 * 86400000)));
  holidays.add(ymd(nthWeekday(year, 5, 0, -1)));
  holidays.add(ymd(observed(new Date(Date.UTC(year, 5, 19)))));
  holidays.add(ymd(observed(new Date(Date.UTC(year, 6, 4)))));
  holidays.add(ymd(nthWeekday(year, 9, 0, 1)));
  holidays.add(ymd(nthWeekday(year, 11, 3, 4)));
  holidays.add(ymd(observed(new Date(Date.UTC(year, 11, 25)))));
  return holidays;
}

export function isTradingDay(d: Date): boolean {
  const wd = d.getUTCDay();
  if (wd === 0 || wd === 6) return false;
  return !nyseHolidays(d.getUTCFullYear()).has(ymd(d));
}

export function nextTradingDay(d: Date): Date {
  let cur = new Date(d.getTime() + 86400000);
  while (!isTradingDay(cur)) cur = new Date(cur.getTime() + 86400000);
  return cur;
}

export function previousTradingDay(d: Date): Date {
  let cur = new Date(d.getTime() - 86400000);
  while (!isTradingDay(cur)) cur = new Date(cur.getTime() - 86400000);
  return cur;
}

/** Mon=0 … Sun=6 matching Python trading_calendar._nth_weekday */
export function nthWeekdayPython(year: number, month: number, weekday: number, n: number): Date {
  return nthWeekday(year, month, weekday, n);
}
