---
cursor:
  subagentId: "bc-a59dc171-4d66-5b1a-a0c8-c2eb15644d45"
---

# Roster correction — keep Grok

Josh: Grok is in the Cursor plan spend family. Restored **A5 → `grok-4.7`**. A1–A4 stay on **`composer-2.5`**.

| Agent | `model_id` |
|-------|------------|
| A1–A4 | `composer-2.5` |
| A5 | `grok-4.7` |

Still excluded: Gemini, Claude, GPT.

## Josh: sync + restart

```powershell
Stop-ScheduledTask -TaskName DayTradeHourlyConsensus -ErrorAction SilentlyContinue
cd $env:DAYTRADE_STORE\scripts\windows
.\Start-HourlyScheduler.ps1 -CatchUp
```
