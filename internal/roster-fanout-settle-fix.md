---
cursor:
  subagentId: "bc-a59dc171-4d66-5b1a-a0c8-c2eb15644d45"
---

# Roster-driven fan-out + settle (fix A2–A5 `no_model` / `proposals_missing`)

## Bug

After single-agent cutover, Windows still looped hard-coded `AGENT_IDS` A1–A5:

- Fan-out: `A1=wrote` + `A2–A5=no_model`
- Settle: `proposals_missing` (wanted A2–A5 JSON that never exist)
- Discord: Issue · settle skipped · … · proposals_missing

1430 tick already has valid `A1.json`; settle was skipped only because of the stale agent list.

## Fix

- New `activeAgentIds()` / `active_agent_ids()` — agents in `state/roster.json` with non-empty `model_id`
- Fan-out, packs, consensus `loadProposals`, orchestrator `proposalsReady`, Python scheduler/run_hourly all use that — **no A1–A5 hard loop**
- Discord fan-out issues no longer fire on `no_model` (retired agents)

## Josh — confirm local roster is A1-only

```powershell
(Get-Content "$env:DAYTRADE_STORE\state\roster.json" -Raw | ConvertFrom-Json).agents.PSObject.Properties.Name
# expect: A1
```

## Josh — sync + restart, then re-settle 14:30

```powershell
# 1) Sync Project store, then restart loop
Stop-ScheduledTask -TaskName DayTradeHourlyConsensus -ErrorAction SilentlyContinue
cd $env:DAYTRADE_STORE\scripts\windows
.\Start-HourlyScheduler.ps1 -CatchUp

# 2) Re-settle the skipped 14:30 tick (A1.json already written)
cd $env:DAYTRADE_STORE\services
npm run orchestrator -- --hour 2026-09-29T14:30 --phase settle
# or: cd $env:DAYTRADE_STORE\scripts; py run_hourly.py --hour 2026-09-29T14:30 --phase settle
```

Or skip re-settle and wait for the next RTH tick after restart.

Expected fan-out log: `A1=wrote/…ms` only (no A2–A5 lines).

See also [fanout completed_no_file fix](/cursor/stores/self/internal/fanout-completed-no-file-fix.md) when SDK finishes without `A1.json`.
