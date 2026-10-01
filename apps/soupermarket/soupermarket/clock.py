"""America/New_York wall clock without third-party zone data."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """weekday: Mon=0 … Sun=6. n>0 counts from the start of the month."""
    d = date(year, month, 1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d + timedelta(days=7 * (n - 1))


def et_offset_hours(day: date) -> int:
    """EDT is UTC-4, EST is UTC-5. DST: second Sunday in March through first Sunday in November."""
    dst_start = _nth_weekday(day.year, 3, 6, 2)
    dst_end = _nth_weekday(day.year, 11, 6, 1)
    if dst_start <= day < dst_end:
        return 4
    return 5


def to_et(now: datetime) -> datetime:
    """Return a naive datetime whose fields are the Eastern wall clock."""
    utc = now.astimezone(timezone.utc)
    off = et_offset_hours(utc.date())
    return utc - timedelta(hours=off)


def et_instant(day: date, hour: int, minute: int = 0) -> datetime:
    """UTC instant for an Eastern wall time on `day`."""
    off = et_offset_hours(day)
    return datetime(day.year, day.month, day.day, hour + off, minute, tzinfo=timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
