---
cursor:
  subagentId: "bc-a59dc171-4d66-5b1a-a0c8-c2eb15644d45"
---

# Roster → Cursor spend bucket (Composer only)

## A1–A5 `model_id` mapping (after Grok correction)

| Agent | Risk | `model_id` |
|-------|------|------------|
| A1 | Very conservative | `composer-2.5` |
| A2 | Conservative | `composer-2.5` |
| A3 | Balanced | `composer-2.5` |
| A4 | Aggressive | `composer-2.5` |
| A5 | Speculative | `grok-4.7` |

Cursor plan family: Composer + Grok. Dropped: Gemini, Claude, GPT. See also `internal/roster-keep-grok.md`.

## Updated

- `state/roster.json` (+ `fanout_spend` note)
- `prompts/A1.md`…`A5.md`
- Docs: `project-context.md`, `orchestration.md`, `daytrade-simulator-plan.md`, `control-plane.md`, `windows-scheduler.md`

Historical state (`sim-meta`, daily analysis, conflict files) left as-is.

## Josh: sync + restart

```powershell
Stop-ScheduledTask -TaskName DayTradeHourlyConsensus -ErrorAction SilentlyContinue
cd $env:DAYTRADE_STORE\scripts\windows
.\Start-HourlyScheduler.ps1 -CatchUp
```

Confirm next `fanout.json` shows A1–A4 `composer-2.5` and A5 `grok-4.7`.
