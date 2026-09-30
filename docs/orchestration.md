# Orchestration — coordinator fan-out

## Hourly model (active)

| Agent | Model ID | Risk |
|-------|----------|------|
| A1 | `grok-4.7` | Medium-aggressive (8% cash / 45% max name / 7 positions) |

A2–A5 are **retired** for hourly fan-out (token spend). Composer is coding-only. Roster: `state/roster.json`.

---

## Daily backfill / live (paused unless resumed)

```bash
cd /cursor/stores/bc-7a9f3369-d383-44f7-b5ec-0d1ac69e76fb/scripts
python run_backfill.py --dry-run --max-days 1
```

Daily five-agent fan-out remains documented historically but is paused. Prefer Mode B hourly single-agent.

---

## Hourly Alpaca paper (single agent)

Plan: [`alpaca-hourly-plan.md`](./alpaca-hourly-plan.md). Settle: [`consensus.md`](./consensus.md).

### Tick playbook (RTH 09:30–15:30 America/New_York half-hours)

```bash
cd /cursor/stores/bc-7a9f3369-d383-44f7-b5ec-0d1ac69e76fb/scripts

# Prefer Node orchestrator (Windows):
#   scripts\windows\Start-HourlyScheduler.ps1 -CatchUp

python run_hourly.py --hour 2026-09-25T14:30 --dry-run --skip-ingest --from-fixtures
```

Orchestrator steps:

1. **Ingest** — live feeds → news cache
2. **Build hour** — cache-only news pack
3. **Reconcile** — Alpaca → `state/book/portfolio.json`
4. **Packs** — `A1.md` only
5. **Fan-out** — one local SDK agent (`grok-4.7`) → `A1.json`
6. **Settle orders** — `consensus.py` / `@daytrade/consensus` with `min_votes=1` (A1 orders or hold)
7. **Validate** — shared caps 8%/45%/7
8. **Submit** — paper ON by default (`--dry-run` to skip)
9. **Journal** — `settle.json`

### Hourly fan-out checklist (A1)

1. System: `prompts/agent_system.md` + `prompts/A1.md`
2. User: hour pack `state/hourly/{date}/{HHMM}/A1.md`
3. Model: `grok-4.7`
4. Write `A1.json` (schema: [`hourly-proposal-schema.md`](./hourly-proposal-schema.md))
5. Empty orders = hold
