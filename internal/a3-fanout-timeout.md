---
cursor:
  subagentId: "bc-a59dc171-4d66-5b1a-a0c8-c2eb15644d45"
---

# A3 fan-out timeout → 20m default

## Evidence (2026-09-29 09:30 ET)

| Metric | Value |
|--------|-------|
| Timeout used | **12 min** (`fanout timeout` on A3) |
| A1/A2/A4/A5 proposal mtime | ~**8.0 min** after `ready_at` |
| A3 proposal mtime | ~**16.4 min** after `ready_at` (wrote ~4.4 min *after* timeout cut the agent) |
| Model | `gemini-3.8-flash` |

`state/hourly/2026-09-29/0930/fanout.json` — A3 `status: error`, `error: fanout timeout`; A3.json still appeared later.

## Change

- Default fan-out / proposal wait: **12 → 20 minutes**
- Still fits 30m cadence (~prep 1–2m + fan-out 20m + settle <1m ≈ leaves ~7–8m slack)
- Override: `DAYTRADE_PROPOSAL_WAIT_MINUTES` in `alpaca.env`, or `--proposal-wait-minutes` / `-ProposalWaitMinutes`
- `fanout.json` now records `started_at`, `timeout_ms`, and per-agent `duration_ms`

## Josh: restart after sync

Yes — restart the Windows loop so it picks up the new default (or set the env and restart):

```powershell
# optional explicit env (defaults already 20 after sync):
# Add-Content "$env:USERPROFILE\.daytrade\alpaca.env" "`nDAYTRADE_PROPOSAL_WAIT_MINUTES=20"

Stop-ScheduledTask -TaskName DayTradeHourlyConsensus -ErrorAction SilentlyContinue
# or close the Start-HourlyScheduler window, then:
cd $env:DAYTRADE_STORE\scripts\windows
.\Start-HourlyScheduler.ps1 -CatchUp
```
