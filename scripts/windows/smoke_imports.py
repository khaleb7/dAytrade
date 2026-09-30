"""Smoke check used by Install-DayTrade.ps1 (keeps Python out of PowerShell -c strings)."""
from __future__ import annotations

import sys
from pathlib import Path

# scripts/windows -> scripts
SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from zoneinfo import ZoneInfo  # noqa: E402

ZoneInfo("America/New_York")

from hourly_scheduler import next_rth_tick  # noqa: E402

d, h, m, t, bucket, slot = next_rth_tick()
print("next_tick={0} slot={1} when={2}".format(bucket, slot, t.isoformat()))
