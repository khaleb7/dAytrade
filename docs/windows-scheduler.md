# Windows installer — DayTrade Alpaca hourly consensus

One-click setup for your **local Windows PC**. Secrets stay in `%USERPROFILE%\.daytrade\alpaca.env` — never in the Project store.

Primary entry is the **Node orchestrator** (`services/orchestrator`). Python remains for news ingest via `@daytrade/news-bridge`. See `docs/control-plane.md`.

## Install (local machine)

1. Copy / sync this Project store onto the PC (any path).
2. Install [Python 3.9+](https://www.python.org/downloads/) with **Add to PATH** (news worker).
3. Install [Node.js 22+](https://nodejs.org/) with **Add to PATH** (control plane / SDK fan-out).
4. Double-click:

   `scripts\windows\Install.bat`

   Or in PowerShell:

   ```powershell
   cd <store>\scripts\windows
   Set-ExecutionPolicy -Scope Process Bypass
   .\Install-DayTrade.ps1 -StartNow
   ```

### What the installer does

| Step | Action |
|------|--------|
| Store | Detects store root; sets user env `DAYTRADE_STORE` |
| Config dir | Creates `%USERPROFILE%\.daytrade\` (env + logs + `config.json`) |
| Secrets | Copies `alpaca.env.example` → `alpaca.env` and opens Notepad if placeholders remain |
| Python | `pip install --user -r requirements.txt` + `tzdata` (news-bridge) |
| Node | `npm install` + `npm run build` under `services/` |
| Smoke | Python zoneinfo + orchestrator `--next-tick`; optional Alpaca `account` GET |
| Task | Registers **DayTradeHourlyConsensus** for the **current user** (no admin). On Access Denied, installs a **Startup folder** shortcut instead. |
| Shortcut | Desktop -> DayTrade Hourly Scheduler (foreground) |

Useful flags:

```powershell
.\Install-DayTrade.ps1 -StoreRoot "D:\daytrade-store" -StartNow
.\Install-DayTrade.ps1 -SkipEnvEdit          # don't open Notepad
.\Install-DayTrade.ps1 -VerifyOnly           # re-check after editing keys
.\Install-DayTrade.ps1 -StartNow             # paper submit ON by default
.\Install-DayTrade.ps1 -DryRun -StartNow     # opt out of paper orders
.\Uninstall-DayTrade.ps1                     # remove task + shortcut
.\Uninstall-DayTrade.ps1 -RemoveEnv          # also delete alpaca.env
```

After install / if `npm run build` failed earlier:

```powershell
cd $env:DAYTRADE_STORE\services
npm install
npm run build
npm run next-tick
cd ..\scripts\windows
.\Install-DayTrade.ps1 -VerifyOnly
```

## If `npm run build` fails on Windows

The installer now vendors Node types under `services/types/` and runs `npm install --include=dev`. Re-run:

```powershell
cd $env:DAYTRADE_STORE\scripts\windows
.\Install-DayTrade.ps1 -VerifyOnly
# or force rebuild:
cd $env:DAYTRADE_STORE\services
npm install --include=dev
npm run build
npx tsx .\orchestrator\src\cli.ts --next-tick
```

Do not use `npm run orchestrator -- --next-tick` in PowerShell — npm eats dashed flags. Use `npx tsx orchestrator\src\cli.ts --next-tick` or `npm run next-tick`.

## After install

1. Confirm keys in `%USERPROFILE%\.daytrade\alpaca.env` (`APCA_*` + `CURSOR_API_KEY`)
2. Optional Discord alerts: set `DAYTRADE_DISCORD_WEBHOOK_URL` in the same `alpaca.env` (see Discord section below)
3. Autostart: `Start-ScheduledTask -TaskName DayTradeHourlyConsensus` **or** log off/on if a Startup shortcut was installed after Access Denied
4. Foreground anytime: `.\Start-HourlyScheduler.ps1 -CatchUp`
5. Status: `<store>\state\scheduler\status.json`
6. Paper submit is **ON** by default. Use `-DryRun` on Start/Install only to skip live paper orders.

## Discord webhook alerts

Optional. Soft-fail: missing/invalid URL or POST errors never block ticks.

1. Add to `%USERPROFILE%\.daytrade\alpaca.env` (outside the store):

   ```
   DAYTRADE_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/<id>/<token>
   ```

2. Restart the scheduler so it reloads env.

3. Smoke test (PowerShell, after `Load-AlpacaEnv.ps1`):

   ```powershell
   . .\Load-AlpacaEnv.ps1
   py -3 $env:DAYTRADE_STORE\scripts\discord_notify.py
   ```

Or one-liner with env already set:

```powershell
py -3 "$env:DAYTRADE_STORE\scripts\discord_notify.py"
```

Events: tick start/end, fan-out/settle issues, **proposal** + submit outcomes, day-end analysis. Details: `internal/discord-webhook-alerts.md`.

## What each tick does

Default phase **`prep-then-settle`**:

1. **Prep** — Python news ingest, hour pack, Alpaca reconcile, `A1.md` + `ready.json`
2. **Fan-out** — one Cursor SDK local agent (`grok-4.7`) writes `A1.json` (fixture if no `CURSOR_API_KEY`)
3. **Settle** — A1 proposal (`min_votes=1`) → book caps 8%/45%/7 → Alpaca paper submit (default). Empty orders = hold. After **15:30 ET**, day-end analysis for next-session packs.
4. Cadence is **30 minutes** (09:30–15:30 ET). Fan-out budget defaults to **20 minutes**. Roster: single **A1** medium-aggressive — see `state/roster.json`.

## Manual / advanced

Foreground (Node orchestrator):

```powershell
cd $env:DAYTRADE_STORE\scripts\windows
.\Start-HourlyScheduler.ps1 -CatchUp
```

Force Python fallback:

```powershell
.\Start-HourlyScheduler.ps1 -CatchUp -UsePythonFallback
```

Re-register only (current user; Startup fallback on Access Denied):

```powershell
.\Register-DayTradeHourly.ps1 -Mode Loop -StoreRoot $env:DAYTRADE_STORE
.\Start-HourlyScheduler.ps1 -CatchUp
```

Per-hour tasks (only if PC timezone is Eastern):

```powershell
.\Register-DayTradeHourly.ps1 -Mode PerHour
```

## Linux cloud VM

```bash
bash scripts/install_scheduler_linux.sh
# Prefer: cd services && npm run orchestrator -- --loop --catch-up
```

## Files

| Path | Role |
|------|------|
| `Install.bat` / `Install-DayTrade.ps1` | **Installer** (Node + Python) |
| `Uninstall-DayTrade.ps1` | Remove task / shortcut |
| `Start-HourlyScheduler.ps1` | Foreground runner → Node orchestrator |
| `Register-DayTradeHourly.ps1` | Task Scheduler registration |
| `Load-AlpacaEnv.ps1` | Load `alpaca.env` (`APCA_` / `DAYTRADE_` / `CURSOR_`) |
| `alpaca.env.example` | Template (no secrets) |
| `../../services/orchestrator` | Primary RTH loop (TS) |
| `../hourly_scheduler.py` | Python fallback |
| `../../docs/control-plane.md` | Service map + fan-out |
