"""America/New_York half-hour bucket helpers for RTH consensus."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List, Tuple

from trading_calendar import _nth_weekday, is_trading_day, parse_day, next_trading_day

# Half-hour RTH ticks: 09:30–15:30 ET (market closes 16:00).
RTH_TICKS: List[Tuple[int, int]] = [
    (9, 30),
    (10, 0),
    (10, 30),
    (11, 0),
    (11, 30),
    (12, 0),
    (12, 30),
    (13, 0),
    (13, 30),
    (14, 0),
    (14, 30),
    (15, 0),
    (15, 30),
]

# Legacy alias — unique hours that appear in RTH_TICKS
RTH_HOURS = (9, 10, 11, 12, 13, 14, 15)


def et_offset_hours(d: date) -> int:
    """US Eastern offset from UTC (4=EDT, 5=EST) for calendar date d in ET."""
    dst_start = _nth_weekday(d.year, 3, 6, 2)
    dst_end = _nth_weekday(d.year, 11, 6, 1)
    return 4 if dst_start <= d < dst_end else 5


def et_offset_iso(d: date) -> str:
    off = et_offset_hours(d)
    return f"-{off:02d}:00"


def slot_key(hour: int, minute: int = 0) -> str:
    if not 0 <= hour <= 23:
        raise ValueError(f"hour must be 0-23, got {hour}")
    if not 0 <= minute <= 59:
        raise ValueError(f"minute must be 0-59, got {minute}")
    return f"{hour:02d}{minute:02d}"


def normalize_slot(hour_or_slot, minute: int = 0) -> str:
    if isinstance(hour_or_slot, int):
        return slot_key(hour_or_slot, minute)
    raw = str(hour_or_slot).strip()
    if len(raw) == 4 and raw.isdigit():
        return raw
    if raw.isdigit() and len(raw) <= 2:
        return slot_key(int(raw), minute)
    for sep in (":", "-"):
        if sep in raw:
            h, m = raw.split(sep, 1)
            return slot_key(int(h), int(m))
    raise ValueError(f"invalid slot {hour_or_slot!r}")


def tick_start_et(day: date, hour: int, minute: int = 0) -> datetime:
    """Timezone-aware datetime at hour:minute America/New_York (fixed offset)."""
    if not 0 <= hour <= 23:
        raise ValueError(f"hour must be 0-23, got {hour}")
    if not 0 <= minute <= 59:
        raise ValueError(f"minute must be 0-59, got {minute}")
    off = et_offset_hours(day)
    tz = timezone(timedelta(hours=-off))
    return datetime(day.year, day.month, day.day, hour, minute, 0, tzinfo=tz)


def hour_start_et(day: date, hour: int) -> datetime:
    """Legacy: hour:00 ET."""
    return tick_start_et(day, hour, 0)


def as_of_iso(day: date, hour: int, minute: int = 0) -> str:
    """ISO bucket string, e.g. 2026-09-25T14:30:00-04:00."""
    return tick_start_et(day, hour, minute).isoformat()


def cutoff_utc(day: date, hour: int, minute: int = 0) -> datetime:
    """Cutoff for news: start of the tick in UTC."""
    return tick_start_et(day, hour, minute).astimezone(timezone.utc)


def bucket_for(day: date, hour: int, minute: int = 0) -> str:
    return f"{day.isoformat()}T{hour:02d}:{minute:02d}"


def parse_hour_bucket(s: str, *, utc: bool = False) -> Tuple[date, int, int, str, str]:
    """Parse half-hour (or hour) bucket.

    Accepts:
      YYYY-MM-DDTHH
      YYYY-MM-DDTHH:MM
      YYYY-MM-DDTHHMM
      YYYY-MM-DDTHH:MM:00[Z|±offset]

    Returns (et_date, et_hour, et_minute, slot_HHMM, as_of_iso).
    """
    s = s.strip().replace(" ", "T")
    if "T" not in s:
        raise ValueError(f"hour bucket must include hour, got {s!r}")

    date_part, rest = s.split("T", 1)
    day = parse_day(date_part)

    offset = None
    body = rest
    if body.endswith("Z"):
        body = body[:-1]
        offset = "+00:00"
    elif len(body) >= 6 and (body[-6] in "+-") and body[-3] == ":":
        offset = body[-6:]
        body = body[:-6]
    elif len(body) >= 5 and (body[-5] in "+-") and body[-3] != ":":
        offset = body[-5:-2] + ":" + body[-2:]
        body = body[:-5]

    minute = 0
    if len(body) == 4 and body.isdigit():
        hour = int(body[:2])
        minute = int(body[2:])
    else:
        parts = body.split(":")
        hour = int(parts[0])
        if len(parts) >= 2 and parts[1] != "":
            minute = int(parts[1])

    if not 0 <= hour <= 23:
        raise ValueError(f"invalid hour in {s!r}")
    if not 0 <= minute <= 59:
        raise ValueError(f"invalid minute in {s!r}")

    if utc or (offset == "+00:00"):
        utc_dt = datetime(day.year, day.month, day.day, hour, minute, 0, tzinfo=timezone.utc)
        for candidate in (day, day - timedelta(days=1), day + timedelta(days=1)):
            off = et_offset_hours(candidate)
            local = utc_dt.astimezone(timezone(timedelta(hours=-off)))
            if local.date() == candidate:
                return (
                    candidate,
                    local.hour,
                    local.minute,
                    slot_key(local.hour, local.minute),
                    as_of_iso(candidate, local.hour, local.minute),
                )
        off = et_offset_hours(day)
        local = utc_dt.astimezone(timezone(timedelta(hours=-off)))
        return (
            local.date(),
            local.hour,
            local.minute,
            slot_key(local.hour, local.minute),
            as_of_iso(local.date(), local.hour, local.minute),
        )

    if offset and offset not in (et_offset_iso(day),):
        sign = 1 if offset[0] == "+" else -1
        oh, om = offset[1:].split(":")
        tz = timezone(timedelta(hours=sign * int(oh), minutes=sign * int(om)))
        dt = datetime(day.year, day.month, day.day, hour, minute, 0, tzinfo=tz)
        off = et_offset_hours(dt.astimezone(timezone.utc).date())
        local = dt.astimezone(timezone(timedelta(hours=-off)))
        return (
            local.date(),
            local.hour,
            local.minute,
            slot_key(local.hour, local.minute),
            as_of_iso(local.date(), local.hour, local.minute),
        )

    return day, hour, minute, slot_key(hour, minute), as_of_iso(day, hour, minute)


def is_rth_consensus_tick(day: date, hour: int, minute: int = 0) -> bool:
    """True if (hour, minute) is a planned RTH consensus tick."""
    return is_trading_day(day) and (hour, minute) in RTH_TICKS


def is_rth_consensus_hour(day: date, hour: int, minute: int = 0) -> bool:
    """Backward-compatible alias for is_rth_consensus_tick."""
    return is_rth_consensus_tick(day, hour, minute)


def next_rth_tick(
    now: datetime | None = None,
) -> Tuple[date, int, int, datetime, str, str]:
    """Return (day, hour, minute, when_et, bucket, slot) for next RTH tick at/after now."""
    if now is None:
        # Approximate "now" in ET via fixed offset of today UTC date (good enough)
        utc_now = datetime.now(timezone.utc)
        for candidate in (
            utc_now.date(),
            utc_now.date() - timedelta(days=1),
            utc_now.date() + timedelta(days=1),
        ):
            off = et_offset_hours(candidate)
            local = utc_now.astimezone(timezone(timedelta(hours=-off)))
            if local.date() == candidate:
                now = local
                break
        else:
            off = et_offset_hours(utc_now.date())
            now = utc_now.astimezone(timezone(timedelta(hours=-off)))

    assert now is not None
    d = now.date()
    now_mins = now.hour * 60 + now.minute
    base = d
    for _ in range(20):
        if is_trading_day(d):
            same = d == base
            for h, m in RTH_TICKS:
                tick_mins = h * 60 + m
                if same and tick_mins < now_mins:
                    continue
                when = tick_start_et(d, h, m)
                return d, h, m, when, bucket_for(d, h, m), slot_key(h, m)
        d = next_trading_day(d)
        base = d
        now_mins = 0
    raise RuntimeError("could not find next RTH tick")
