---
cursor:
  subagentId: "bc-a59dc171-4d66-5b1a-a0c8-c2eb15644d45"
---

# Fix: `completed_no_file` → settle skipped (1530 example)

## What happened (2026-09-29T15:30)

- Fan-out: Grok SDK run finished (~114s) but **`A1.json` never appeared** at `state/hourly/2026-09-29/1530/A1.json`
- Status was `completed_no_file` (treated as soft success) → Discord Issue · fan-out
- Settle: `proposals_missing` → Discord Issue · settle skipped
- Tick end still showed `ok · fanout=sdk_local` because `report.error` was unset

1430 same day **did** have `A1.json` — 1530 agent likely returned JSON in chat/tools without persisting to the canonical path.

## Fix

`services/fanout/src/proposalRecovery.ts` + fan-out loop:

1. **Pre-create** proposal dir before SDK run
2. **Drain SDK stream** — capture `text-delta` + `write` tool payloads
3. **`ensureProposalFile`** — canonical path via:
   - existing file
   - write-tool `fileText`
   - misplaced `A1.json` under same day
   - JSON parsed from stream / fenced blocks
4. Success → `wrote` or `wrote_<source>`; failure → **`error`** (not `completed_no_file`)
5. Prompt requires Write tool to **absolute** `state/hourly/.../A1.json`
6. Orchestrator: `report.error = proposals_missing` when settle skips; tick end no longer “ok” on that path

## Josh — sync + restart

```powershell
Stop-ScheduledTask -TaskName DayTradeHourlyConsensus -ErrorAction SilentlyContinue
cd $env:DAYTRADE_STORE\scripts\windows
.\Start-HourlyScheduler.ps1 -CatchUp
```

## Josh — re-run 15:30 (no `A1.json` on disk today)

Sync first, then **re-fan-out** (Grok) + settle (skip re-ingest):

```powershell
cd $env:DAYTRADE_STORE\services
npm run orchestrator -- --hour 2026-09-29T15:30 --phase fanout
npm run orchestrator -- --hour 2026-09-29T15:30 --phase settle
```

Or wait for the next RTH tick after restart.

Roster check (A1 only):

```powershell
(Get-Content "$env:DAYTRADE_STORE\state\roster.json" -Raw | ConvertFrom-Json).agents.PSObject.Properties.Name
```
