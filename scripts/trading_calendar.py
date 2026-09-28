"""NYSE trading-day calendar helpers (weekends + common holidays)."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional, Set


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """weekday: Mon=0 … Sun=6. n=1 first, n=-1 last."""
    if n > 0:
        d = date(year, month, 1)
        while d.weekday() != weekday:
            d += timedelta(days=1)
        d += timedelta(weeks=n - 1)
        return d
    # last
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def observed(d: date) -> date:
    """Saturday → Friday before; Sunday → Monday after (US federal style)."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def nyse_holidays(year: int) -> Set[date]:
    """Approximate NYSE full-day holidays for a calendar year."""
    holidays: Set[date] = set()
    holidays.add(observed(date(year, 1, 1)))  # New Year's Day
    holidays.add(_nth_weekday(year, 1, 0, 3))  # MLK Day
    holidays.add(_nth_weekday(year, 2, 0, 3))  # Presidents' Day
    # Good Friday — approximate via Easter (Anonymous Gregorian)
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    easter = date(year, month, day)
    holidays.add(easter - timedelta(days=2))  # Good Friday
    holidays.add(_nth_weekday(year, 5, 0, -1))  # Memorial Day
    holidays.add(observed(date(year, 6, 19)))  # Juneteenth
    holidays.add(observed(date(year, 7, 4)))  # Independence Day
    holidays.add(_nth_weekday(year, 9, 0, 1))  # Labor Day
    holidays.add(_nth_weekday(year, 11, 3, 4))  # Thanksgiving
    holidays.add(observed(date(year, 12, 25)))  # Christmas
    return holidays


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    return d not in nyse_holidays(d.year)


def parse_day(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def next_trading_day(d: date) -> date:
    cur = d + timedelta(days=1)
    while not is_trading_day(cur):
        cur += timedelta(days=1)
    return cur


def prev_trading_day(d: date) -> date:
    cur = d - timedelta(days=1)
    while not is_trading_day(cur):
        cur -= timedelta(days=1)
    return cur


def trading_days(start: date, end: date) -> List[date]:
    """Inclusive list of NYSE trading days from start through end."""
    if end < start:
        return []
    out: List[date] = []
    cur = start
    while cur <= end:
        if is_trading_day(cur):
            out.append(cur)
        cur += timedelta(days=1)
    return out


def rth_open_utc_iso(d: date | str) -> str:
    """US RTH open ≈ 09:30 America/New_York. Return ISO UTC bound (no lookahead cutoff)."""
    # Fixed offset approximation: EDT (UTC-4) Mar–Nov, EST (UTC-5) otherwise.
    # Good enough for pre-open news filtering without pytz dependency.
    # DST: second Sunday March → first Sunday November.
    if isinstance(d, str):
        d = parse_day(d)
    dst_start = _nth_weekday(d.year, 3, 6, 2)
    dst_end = _nth_weekday(d.year, 11, 6, 1)
    offset_hours = 4 if dst_start <= d < dst_end else 5
    # 09:30 local → UTC
    hour_utc = 9 + offset_hours
    minute = 30
    if hour_utc >= 24:
        # shouldn't happen for US
        hour_utc -= 24
    return f"{d.isoformat()}T{hour_utc:02d}:{minute:02d}:00Z"


def main(argv: Optional[Iterable[str]] = None) -> int:
    p = argparse.ArgumentParser(description="NYSE trading calendar utilities")
    p.add_argument("--is-trading-day", metavar="YYYY-MM-DD")
    p.add_argument("--next", metavar="YYYY-MM-DD", dest="next_of")
    p.add_argument("--range", nargs=2, metavar=("START", "END"))
    args = p.parse_args(list(argv) if argv is not None else None)

    if args.is_trading_day:
        d = parse_day(args.is_trading_day)
        print("yes" if is_trading_day(d) else "no")
        return 0
    if args.next_of:
        print(next_trading_day(parse_day(args.next_of)).isoformat())
        return 0
    if args.range:
        start, end = parse_day(args.range[0]), parse_day(args.range[1])
        for d in trading_days(start, end):
            print(d.isoformat())
        return 0
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
