---
cursor:
  subagentId: "bc-a59dc171-4d66-5b1a-a0c8-c2eb15644d45"
---

# Consensus ≥2 + paper submit default

## Changes

- **`MIN_VOTES = 2`** in `services/consensus/src` + `dist`, and `scripts/consensus.py`
- **Paper Alpaca submit ON by default**; `--dry-run` / `--no-submit` / `-DryRun` opt out
  - Node: `services/orchestrator/src/cli.ts` + `dist/cli.js` (`submit = true`)
  - `runHour`: `opts.submit !== false`
  - Python: `run_hourly.py`, `hourly_scheduler.py`
  - Windows: `Start-HourlyScheduler.ps1`, `Install-DayTrade.ps1`, `Register-DayTradeHourly.ps1`
- Docs: `consensus.md`, `control-plane.md`, `windows-scheduler.md`, `orchestration.md`, `project-context.md`, `alpaca-hourly-plan.md`
- Rewrote `state/hourly/2026-09-28/15/consensus.json` → **buy VTI $150 (2 votes: A3, A4)**

## Windows next step

After Agent Store sync:

```powershell
cd $env:DAYTRADE_STORE\scripts\windows
.\Start-HourlyScheduler.ps1 -Once -Hour 2026-09-28T15 -Phase settle
```

Expect paper market buy VTI (not dry-run). Use `-DryRun` only to skip.
