---
cursor:
  subagentId: "bc-a59dc171-4d66-5b1a-a0c8-c2eb15644d45"
---

# 30-minute RTH buckets + day-end analysis

## Cadence

- Ticks: **09:30–15:30 ET** every 30 minutes (13 ticks/day)
- Bucket CLI: `YYYY-MM-DDTHH:MM` (also `THHMM`, legacy `THH` → `:00`)
- State dirs: `state/hourly/YYYY-MM-DD/HHMM/` (legacy `HH` still readable when minute=00)
- Fan-out / proposal wait default: **20 minutes** (was 12; A3/`gemini-3.8-flash` observed ~16.4m on 2026-09-29 09:30 — see `internal/a3-fanout-timeout.md`)

## Day-end analysis

- Script: `scripts/day_end_analysis.py --date YYYY-MM-DD`
- Writes: `state/daily/YYYY-MM-DD/analysis.json` + `analysis.md`
- Appends anonymized lesson to `state/lessons/ledger.jsonl`
- Auto-runs after **15:30** settle (Node orchestrator + Python scheduler)
- Packs inject `{{DAY_END_ANALYSIS}}` from the latest prior trading-day analysis into every fan-out prompt

## Windows after sync

Restart the loop so it picks up the new tick list:

```powershell
Stop-ScheduledTask -TaskName DayTradeHourlyConsensus -ErrorAction SilentlyContinue
# or close the Start-HourlyScheduler window, then:
cd $env:DAYTRADE_STORE\scripts\windows
.\Start-HourlyScheduler.ps1 -CatchUp
```

Confirm `state\scheduler\status.json` shows `"cadence":"30m"` and next tick at `:00` or `:30`.
