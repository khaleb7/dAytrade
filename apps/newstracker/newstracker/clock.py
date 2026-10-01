"""Eastern calendar day for bar timestamps. DST matches the trader clock."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _nth_sunday(year: int, month: int, n: int) -> datetime:
    d = datetime(year, month, 1, tzinfo=timezone.utc)
    d = d + timedelta(days=(6 - d.weekday()) % 7 + 7 * (n - 1))
    return d


def et_offset_hours(dt: datetime) -> int:
    dt = dt.astimezone(timezone.utc)
    start = _nth_sunday(dt.year, 3, 2).date()
    end = _nth_sunday(dt.year, 11, 1).date()
    if start <= dt.date() < end:
        return 4
    return 5


def et_day(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    local = dt - timedelta(hours=et_offset_hours(dt))
    return local.strftime("%Y-%m-%d")
