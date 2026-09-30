---
cursor:
  subagentId: "bc-a59dc171-4d66-5b1a-a0c8-c2eb15644d45"
---

# Discord webhook alerts

## Env

- **Name:** `DAYTRADE_DISCORD_WEBHOOK_URL`
- **Where:** `%USERPROFILE%\.daytrade\alpaca.env` (same loader as Alpaca/Cursor keys)
- **Policy:** never commit the webhook URL; examples only have a commented placeholder
- Soft-fail: unset / bad shape / HTTP errors log a warning and continue

## What fires

| Event | When |
|-------|------|
| Tick start | Each `runHour` / Python `run_hourly` begin |
| Tick skipped | Outside RTH half-hour ticks |
| Issue · news / ingest | Prep/news failure |
| Issue · fan-out | Agent error / no_model / completed_no_file |
| Issue · settle skipped | Missing proposals or settle skip |
| Consensus / Proposal | Settle: A1 orders (side/symbol/size) or hold |
| Submit | Follow-up after proposal (paper / dry-run / skipped hold) |
| Tick end | Compact summary after tick |
| Day-end | After 15:30 analysis (start + done) |
| Issue · loop | Uncaught exception in loop |

## Code

- TS: `services/shared/src/discord.ts` → orchestrator fire-and-forget
- Python: `scripts/discord_notify.py` → `run_hourly.py` / `hourly_scheduler.py` fallback

## Josh setup (PowerShell)

Append the real webhook (do **not** put it in the store):

```powershell
Add-Content -Path "$env:USERPROFILE\.daytrade\alpaca.env" -Value "`nDAYTRADE_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/<id>/<token>"
```

Test:

```powershell
cd $env:DAYTRADE_STORE\scripts\windows
. .\Load-AlpacaEnv.ps1
py -3 ..\discord_notify.py
```

Restart the hourly loop after adding the var.
