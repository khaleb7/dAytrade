---
cursor:
  subagentId: "bc-a59dc171-4d66-5b1a-a0c8-c2eb15644d45"
---

# Market signals (VIX / bonds / oil) — pack context only

## Source

`scripts/fetch_signals.py` via **yfinance** (same stack as `fetch_market.py`):

| Signal | Yahoo | Pack role |
|--------|-------|-----------|
| VIX | `^VIX` | vol regime |
| US 10Y yield | `^TNX` | rates |
| US 13W T-bill | `^IRX` | short-rate proxy |
| TLT | `TLT` | bond ETF level |
| WTI | `CL=F` | oil |
| USO | `USO` | oil ETF proxy |

Cache: `state/signals/latest.json` + per-tick `state/hourly/…/HHMM/signals.json`.

## Wiring

- Soft-fail on every prep: Node `news-bridge` `buildHour` → `fetchMarketSignals`; Python `run_hourly` step `signals`
- Packs inject `{{MARKET_SIGNALS}}` + `{{VIX}}` (`services/packs`, `scripts/build_hourly_packs.py`, `prompts/hourly_input_template.md`)
- Missing signals do **not** fail the tick

## Not tradeable

Blocked in `validate_batch` / `validate_book` / `@daytrade/book`: `VIX`, `VXX`, `UVXY`, other vol products, and any `=` / `^` futures/index forms.

**TLT** and **USO** stay normal US ETFs under existing book rules if agents propose them — they are included as signal levels, not auto-traded.

## Windows

After store sync, restart the loop (or wait for next tick if already on tsx src). No installer change required.
