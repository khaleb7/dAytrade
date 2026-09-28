---
cursor:
  subagentId: "bc-a59dc171-4d66-5b1a-a0c8-c2eb15644d45"
---

# Alpaca hourly consensus — implementation summary

## Status

All plan todos implemented. Daily backfill untouched / still paused. Plan file not edited. No Kubespray PR. Secrets never written to the store.

## How to run

```bash
cd /cursor/stores/bc-7a9f3369-d383-44f7-b5ec-0d1ac69e76fb/scripts

# Shell only — never put keys in store files
export APCA_API_KEY_ID=…
export APCA_API_SECRET_KEY=…
export APCA_API_BASE_URL=https://paper-api.alpaca.markets

# Smoke: fixture proposals → majority/median consensus, no submit
python3 run_hourly.py --hour 2026-09-25T14 --dry-run --skip-ingest --from-fixtures --skip-reconcile

# Live tick skeleton (ingest + packs; then fan-out agents externally)
python3 run_hourly.py --hour YYYY-MM-DDTHH --dry-run
# After A1.json…A5.json land:
python3 run_hourly.py --hour YYYY-MM-DDTHH --skip-ingest --skip-packs --skip-news --dry-run

# Paper submit (explicit; defaults off)
python3 run_hourly.py --hour YYYY-MM-DDTHH --skip-ingest --skip-packs --skip-news --submit

# Pieces
python3 fetch_news.py ingest --live-feeds
python3 fetch_news.py build-hour YYYY-MM-DDTHH
python3 alpaca_client.py account          # GET only
python3 alpaca_client.py reconcile        # → state/book/portfolio.json
python3 consensus.py --bucket YYYY-MM-DDTHH
python3 validate_book.py state/hourly/…/consensus.json --book state/book/portfolio.json --prices …
```

## Paths added/updated

### Docs
- `docs/project-context.md` — daily + hourly modes
- `docs/consensus.md` — majority ≥3/5, median, 15%/35%/6, holds
- `docs/hourly-proposal-schema.md`
- `docs/orchestration.md` — hourly fan-out + Alpaca playbook
- `docs/news-cache.md` — brief `build-hour` / live ingest notes
- Plan file **not** edited

### Scripts
- `scripts/hour_bucket.py`
- `scripts/fetch_news.py` — `build-hour` (+ live ingest already present)
- `scripts/alpaca_client.py` — env auth, account/positions/orders/cancel/reconcile
- `scripts/consensus.py`
- `scripts/validate_book.py`
- `scripts/build_hourly_packs.py`
- `scripts/run_hourly.py` — `--dry-run` default; `--submit` off by default
- `scripts/paths.py` — hourly/book/alpaca paths
- `scripts/requirements.txt` — note urllib REST (optional alpaca-py)

### Prompts / fixtures / state
- `prompts/hourly_input_template.md`
- `prompts/agent_system.md` — hourly propose-only note
- `fixtures/hourly/proposals/A1–A5.json`, `news.json`, `book/`, `prices.json`
- `state/alpaca/config.json` — paper, base URL, target equity 1000 (**no secrets**)
- `state/book/portfolio.json` — Alpaca mirror (reconciled in smoke)
- `state/hourly/…` — smoke outputs

## Smoke results

| Check | Result |
|-------|--------|
| Consensus majority | **VTI buy** votes=3 (A2/A3/A4); QQQ/SPY rejected (1 vote each) |
| Median size | notional **50.0** (40/50/60) |
| Holds | A1 empty orders did not block VTI |
| `validate_book` | ok; post cash 950 / VTI 0.2 @ 250 |
| `run_hourly --from-fixtures --dry-run` | consensus + validate + `dry_run_skip` submit; **no orders placed** |
| `build-hour` cache | 2026-09-16T14 → 28 items from 3246 cache rows |
| Alpaca GET account | **ACTIVE**; equity **100000**, cash **100000** (paper default, not $1000) |
| Reconcile | wrote `state/book/portfolio.json`; 0 positions |
| Secrets in store | raw key/secret strings **absent** |

## Windows scheduler

- [`docs/windows-scheduler.md`](../docs/windows-scheduler.md) — Windows Task Scheduler / loop + **Linux tmux install**
- `scripts/hourly_scheduler.py` — RTH loop / `--once` / prep-then-settle
- `scripts/windows/` — `Start-HourlyScheduler.ps1`, `Register-DayTradeHourly.ps1`, `alpaca.env.example`
- `scripts/install_scheduler_linux.sh` — tmux install for this Linux VM
- `run_hourly.py --phase prep|settle|full`

### Windows local installer

- `scripts/windows/Install.bat` + `Install-DayTrade.ps1` — one-shot setup (env, pip, Task Scheduler, shortcut)
- `scripts/windows/Uninstall-DayTrade.ps1`
- Docs: [`docs/windows-scheduler.md`](../docs/windows-scheduler.md)

On local PC: sync store → double-click `Install.bat` → fill `%USERPROFILE%\.daytrade\alpaca.env` → `Start-ScheduledTask -TaskName DayTradeHourlyConsensus`

- Deps: `pip install --user -r requirements.txt tzdata`
- Env: `/home/ubuntu/.daytrade/alpaca.env` (mode 600, **outside** store)
- Process: tmux session `daytrade-hourly` → waiting for **2026-09-28T10 ET**
- Logs: `~/.daytrade/logs/scheduler.log`
- Status: `state/scheduler/status.json`
- Reinstall: `bash ~/.daytrade/install_scheduler_linux.sh` (or `bash scripts/install_scheduler_linux.sh`)
- Dry-run only (no `--submit`)

## Paper sizing offset (−$99,000)

`state/alpaca/config.json` → `"equity_offset_usd": -99000` maps Alpaca’s $100k paper default onto a ~$1000 sizing book.

- `alpaca_client.sizing_book()` — cash/equity + offset; positions unchanged
- Hourly packs show the sizing view (`broker_*` = raw)
- `validate_book` applies offset by default (caps/affordability on ~$1000)
- Broker submits still use proposal notionals/qtys as-is
- Fixtures already at ~$1000 skip the offset (avoid negative cash)

Reconcile annotates `sizing_cash_usd` / `sizing_equity_usd` on `state/book/portfolio.json`.
