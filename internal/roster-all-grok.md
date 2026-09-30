---
cursor:
  subagentId: "bc-a59dc171-4d66-5b1a-a0c8-c2eb15644d45"
---

# Roster — all agents `grok-4.7`

Josh: Composer is for coding, not trading. A1–A5 all use **`grok-4.7`**. Risk tiers unchanged (cash floors / caps / prompts).

| Agent | Risk | `model_id` |
|-------|------|------------|
| A1 | Very conservative | `grok-4.7` |
| A2 | Conservative | `grok-4.7` |
| A3 | Balanced | `grok-4.7` |
| A4 | Aggressive | `grok-4.7` |
| A5 | Speculative | `grok-4.7` |

## Josh: sync + restart

```powershell
Stop-ScheduledTask -TaskName DayTradeHourlyConsensus -ErrorAction SilentlyContinue
cd $env:DAYTRADE_STORE\scripts\windows
.\Start-HourlyScheduler.ps1 -CatchUp
```
