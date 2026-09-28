"""America/New_York hour-bucket helpers for hourly consensus."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Tuple

from trading_calendar import _nth_weekday, is_trading_day, parse_day


def et_offset_hours(d: date) -> int:
    """US Eastern offset from UTC (4=EDT, 5=EST) for calendar date d in ET."""
    dst_start = _nth_weekday(d.year, 3, 6, 2)
    dst_end = _nth_weekday(d.year, 11, 6, 1)
    return 4 if dst_start <= d < dst_end else 5


def et_offset_iso(d: date) -> str:
    off = et_offset_hours(d)
    return f"-{off:02d}:00"


def hour_start_et(day: date, hour: int) -> datetime:
    """Timezone-aware datetime at hour:00 America/New_York (fixed offset)."""
    if not 0 <= hour <= 23:
        raise ValueError(f"hour must be 0-23, got {hour}")
    off = et_offset_hours(day)
    tz = timezone(timedelta(hours=-off))
    return datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=tz)


def as_of_iso(day: date, hour: int) -> str:
    """ISO hour bucket string, e.g. 2026-09-25T14:00:00-04:00."""
    return hour_start_et(day, hour).isoformat()


def cutoff_utc(day: date, hour: int) -> datetime:
    """Cutoff for news: start of the hour in UTC."""
    return hour_start_et(day, hour).astimezone(timezone.utc)


def parse_hour_bucket(s: str, *, utc: bool = False) -> Tuple[date, int, str]:
    """Parse hour bucket.

    Accepts:
      YYYY-MM-DDTHH
      YYYY-MM-DDTHH:00
      YYYY-MM-DDTHH:00:00
      YYYY-MM-DDTHH:00:00Z / ±offset
      YYYY-MM-DD HH

    Default: HH is America/New_York local hour.
    With utc=True: HH is UTC hour (converted to ET date/hour for paths).

    Returns (et_date, et_hour, as_of_iso).
    """
    s = s.strip().replace(" ", "T")
    if "T" not in s:
        raise ValueError(f"hour bucket must include hour, got {s!r}")

    date_part, rest = s.split("T", 1)
    day = parse_day(date_part)

    # Strip Z / offset for hour parse; keep offset if present
    offset = None
    body = rest
    if body.endswith("Z"):
        body = body[:-1]
        offset = "+00:00"
    elif len(body) >= 6 and (body[-6] in "+-") and body[-3] == ":":
        offset = body[-6:]
        body = body[:-6]
    elif len(body) >= 5 and (body[-5] in "+-") and body[-3] != ":":
        # ±HHMM
        offset = body[-5:-2] + ":" + body[-2:]
        body = body[:-5]

    parts = body.split(":")
    hour = int(parts[0])
    if not 0 <= hour <= 23:
        raise ValueError(f"invalid hour in {s!r}")

    if utc or (offset == "+00:00"):
        # Interpret as UTC wall time → convert to ET
        utc_dt = datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=timezone.utc)
        # Convert using ET offset of the UTC calendar date (good enough for RTH)
        # Better: try both candidate ET dates
        for candidate in (day, day - timedelta(days=1), day + timedelta(days=1)):
            off = et_offset_hours(candidate)
            local = utc_dt.astimezone(timezone(timedelta(hours=-off)))
            if local.date() == candidate:
                return candidate, local.hour, as_of_iso(candidate, local.hour)
        off = et_offset_hours(day)
        local = utc_dt.astimezone(timezone(timedelta(hours=-off)))
        return local.date(), local.hour, as_of_iso(local.date(), local.hour)

    if offset and offset not in (et_offset_iso(day),):
        # Explicit non-ET offset: convert to ET
        sign = 1 if offset[0] == "+" else -1
        oh, om = offset[1:].split(":")
        tz = timezone(timedelta(hours=sign * int(oh), minutes=sign * int(om)))
        dt = datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=tz)
        off = et_offset_hours(dt.astimezone(timezone.utc).date())
        local = dt.astimezone(timezone(timedelta(hours=-off)))
        return local.date(), local.hour, as_of_iso(local.date(), local.hour)

    return day, hour, as_of_iso(day, hour)


def is_rth_consensus_hour(day: date, hour: int) -> bool:
    """True if hour is a planned consensus tick (10–15 ET on a trading day)."""
    return is_trading_day(day) and 10 <= hour <= 15
