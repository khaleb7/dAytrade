---
cursor:
  subagentId: "bc-a59dc171-4d66-5b1a-a0c8-c2eb15644d45"
---

# Discord consensus summaries

## What was wrong

Consensus Discord events **did fire** on settle, but the body was sparse (`no_consensus` + `orders: 0`). `steps.consensus` omitted `rejected_legs` / `proposals_loaded` / `min_votes`, so rejected below-majority legs never reached Discord.

## Fix

- Node `notifyTickOutcome` + Python `_notify_tick_outcome`: rich consensus embed
  - loaded agents · min_votes
  - orders: `buy SYM $N (Nv:A?,A?)` / sells with qty
  - or `no_consensus` + rejected legs (or “all holds”)
- Submit always follows as a paired message (`Submit · skipped/paper/dry-run`)
- Soft-fail unchanged

## Josh: sync + restart

```powershell
Stop-ScheduledTask -TaskName DayTradeHourlyConsensus -ErrorAction SilentlyContinue
cd $env:DAYTRADE_STORE\scripts\windows
.\Start-HourlyScheduler.ps1 -CatchUp
```

Confirm webhook still in `%USERPROFILE%\.daytrade\alpaca.env` as `DAYTRADE_DISCORD_WEBHOOK_URL`.
