# Orchestration — coordinator fan-out

How the Project coordinator runs trading sessions for agents A1–A5.

## Models (locked)

| Agent | Model ID |
|-------|----------|
| A1 | `gpt-5.6-sol-medium` |
| A2 | `claude-sonnet-5-thinking-medium` |
| A3 | `gemini-3.8-flash-medium` |
| A4 | `claude-opus-5-thinking-medium` |
| A5 | `grok-4.7-medium` |

Roster mirror: `state/roster.json`.

---

## Daily backfill / live (paused unless resumed)

```bash
cd /cursor/stores/bc-7a9f3369-d383-44f7-b5ec-0d1ac69e76fb/scripts
python run_backfill.py --dry-run --max-days 1   # smoke / no LLMs
python run_backfill.py --network --max-days 20  # real packs; still needs agent batches
```

For full LLM backfill, each day:

1. Ensure `state/market/YYYY-MM-DD.json` and `state/news/YYYY-MM-DD.json`.
2. Build five daily packs from `prompts/daily_input_template.md`.
3. Fan out five cloud agents **in parallel**, each with its model ID above.
4. Write returns to `state/batches/YYYY-MM-DD/A1.json` … `A5.json`.
5. `python settle_day.py --date YYYY-MM-DD`
6. Advance / checkpoint via `run_backfill.py` or update `state/sim-meta.json`.

### Daily fan-out checklist (per agent)

1. System: `prompts/agent_system.md` + `prompts/A?.md`
2. User: filled `prompts/daily_input_template.md`
3. Model: roster model ID (do not substitute)
4. Persist raw JSON batch only to `state/batches/{date}/{agent}.json`
5. Do not share one agent’s portfolio with another — only anonymized `state/lessons/ledger.jsonl`

Validation: `scripts/validate_batch.py` — **reject whole batch** on any rule failure → agent holds.

---

## Hourly Alpaca paper consensus (active)

Plan: [`alpaca-hourly-plan.md`](./alpaca-hourly-plan.md). Consensus: [`consensus.md`](./consensus.md).

### Tick playbook (RTH 10:00–15:00 America/New_York)

```bash
cd /cursor/stores/bc-7a9f3369-d383-44f7-b5ec-0d1ac69e76fb/scripts

# Full dry hour (no Alpaca submit) — fixture proposals prove majority/median
python run_hourly.py --hour 2026-09-25T14 --dry-run --skip-ingest --from-fixtures

# Live tick skeleton (ingest + packs; fan-out is coordinator / --proposals-dir)
export APCA_API_KEY_ID=…          # shell only — never store
export APCA_API_SECRET_KEY=…
python run_hourly.py --hour 2026-09-25T14 --dry-run
# After agents write A1.json…A5.json:
python run_hourly.py --hour 2026-09-25T14 --skip-ingest --skip-packs --dry-run
# Submit only when intentionally enabling (defaults off):
python run_hourly.py --hour 2026-09-25T14 --skip-ingest --skip-packs --submit
```

Orchestrator steps inside `run_hourly.py`:

1. **Ingest** (unless `--skip-ingest`) — `fetch_news.py ingest --live-feeds` into `state/news_cache/` (backoff; no DOC hammer).
2. **Build hour** — cache-only news → `state/hourly/YYYY-MM-DD/HH/news.json`.
3. **Reconcile book** (if keys present) — Alpaca account/positions → `state/book/portfolio.json`.
4. **Packs** (unless `--skip-packs`) — `build_hourly_packs.py` writes `A1.md`…`A5.md`.
5. **Fan-out** — coordinator launches five cloud agents (see checklist below). `--from-fixtures` copies fixture proposals for smoke. Optional placeholder note if proposals missing.
6. **Consensus** — `consensus.py` → `consensus.json` (majority ≥3/5, median size).
7. **Validate** — `validate_book.py` shared caps 15%/35%/6; fail → hold.
8. **Submit** — only with `--submit` (and not `--dry-run`). Default is dry-run / no orders.
9. **Journal** — write `settle.json` with proposals summary, consensus, validation, optional fills.

### Hourly fan-out checklist (per agent)

1. System: `prompts/agent_system.md` + `prompts/A?.md` (note: propose only; consensus executes)
2. User: filled hour pack `state/hourly/{date}/{HH}/A?.md` (from `prompts/hourly_input_template.md`)
3. Model: roster model ID (do not substitute)
4. Persist raw JSON proposal to `state/hourly/{date}/{HH}/A?.json` (schema: [`hourly-proposal-schema.md`](./hourly-proposal-schema.md))
5. Shared book snapshot only — do not reveal other agents’ proposals
6. Agents must **not** assume fills; empty `"orders": []` is OK

### Alpaca credentials

| Env | Required | Notes |
|-----|----------|-------|
| `APCA_API_KEY_ID` | for live API | Paper key |
| `APCA_API_SECRET_KEY` | for live API | Paper secret |
| `APCA_API_BASE_URL` | no | Default `https://paper-api.alpaca.markets` |

`state/alpaca/config.json` holds paper flag / base URL / target equity **1000** — **no secrets**.

## Windows PC scheduler

**Installer (local Windows):** copy/sync the store, then double-click `scripts\windows\Install.bat`  
Full guide: [`windows-scheduler.md`](./windows-scheduler.md).

```powershell
cd <store>\scripts\windows
.\Install-DayTrade.ps1 -StartNow          # dry-run logon task
.\Install-DayTrade.ps1 -VerifyOnly        # after editing alpaca.env
.\Uninstall-DayTrade.ps1
```

Keys go in `%USERPROFILE%\.daytrade\alpaca.env` only. Or foreground: `.\Start-HourlyScheduler.ps1 -CatchUp`  
Python: `python hourly_scheduler.py` (RTH 10–15 ET; default prep → wait for proposals → dry-run settle).
