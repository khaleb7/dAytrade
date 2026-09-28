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
.\Install-DayTrade.ps1 -Submit -StartNow     # paper orders ON (only when ready)
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
2. Autostart: `Start-ScheduledTask -TaskName DayTradeHourlyConsensus` **or** log off/on if a Startup shortcut was installed after Access Denied
3. Foreground anytime: `.\Start-HourlyScheduler.ps1 -CatchUp`
4. Status: `<store>\state\scheduler\status.json`
5. Keep **dry-run** until a clean hour; then re-run installer with `-Submit`

## What each tick does

Default phase **`prep-then-settle`**:

1. **Prep** — Python news ingest, hour pack, Alpaca reconcile, `A1.md`…`A5.md` + `ready.json`
2. **Fan-out** — Cursor SDK local agents (roster `model_id`) write `A1.json`…`A5.json` (fixtures if no `CURSOR_API_KEY`)
3. **Settle** — consensus → book caps (with −$99k sizing offset) → dry-run / `--submit`

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
