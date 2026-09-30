---
cursor:
  subagentId: "bc-a59dc171-4d66-5b1a-a0c8-c2eb15644d45"
---

# Single Grok agent (medium-aggressive)

Josh: 5-way fan-out token spend not worth it → **one** `grok-4.7` agent every RTH tick.

## Chosen risk (medium-aggressive)

Between prior A3 balanced (15%/35%/6) and A4 aggressive (5%/50%/8):

| Cap | Value |
|-----|-------|
| Cash floor | **8%** |
| Max single name | **45%** |
| Max positions | **7** |

Agent id kept as **A1** (sole hourly trader). Model: `grok-4.7`.

## What replaced ≥2 consensus

- **Before:** ≥2 of 5 agents agree on `(symbol, side)`; median size among voters.
- **After:** `min_votes=1` — A1’s valid orders **are** the book proposal. Empty `orders` = **hold** (valid).
- Legacy file `consensus.json` kept; Discord titles say **Proposal** (not multi-agent consensus).
- Shared book validator still runs (caps above, whole-batch reject).

## Touched

- `state/roster.json` — A1 only + `book_caps` 8/45/7 + `fanout_spend.mode=single_agent`
- `AGENT_IDS=["A1"]` — shared TS + Python packs/run_hourly/consensus/fanout
- Cap constants — `validate_book.py`, `@daytrade/book`
- Prompts — `A1.md` live; A2–A5 retired stubs; `agent_system.md` + hourly template
- Discord — Proposal + Submit (hold path); mode field `single`
- Docs — consensus, orchestration, alpaca-hourly-plan, project-context, control-plane, windows-scheduler, preferences

## Josh — sync + restart Windows loop

```powershell
# Pull / sync the Project store, then:
Stop-ScheduledTask -TaskName DayTradeHourlyConsensus -ErrorAction SilentlyContinue
cd $env:DAYTRADE_STORE\scripts\windows
.\Start-HourlyScheduler.ps1 -CatchUp
```

If sync lags, patch local roster so only A1 runs:

```powershell
# Ensure state\roster.json has only agents.A1 (grok-4.7, 8/45/7) matching store
# Then restart the scheduler as above
```

Confirm `CURSOR_API_KEY` still in `%USERPROFILE%\.daytrade\alpaca.env` (single fan-out still needs it).
