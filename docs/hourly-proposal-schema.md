# Hourly proposal schema

Same shape as the daily [batch schema](./batch-schema.md), except `as_of` is an **ISO hour bucket** (not a calendar date). Agents **propose only**; fills happen only if consensus + book validation pass and the orchestrator submits to Alpaca paper.

## Schema

```json
{
  "agent_id": "A3",
  "as_of": "2026-09-25T14:00:00-04:00",
  "orders": [
    {"side": "buy", "symbol": "VTI", "notional_usd": 50.0},
    {"side": "sell", "symbol": "AAPL", "qty": 0.15}
  ],
  "thesis": "Short rationale for this hour’s proposal."
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `agent_id` | string | yes | One of `A1`…`A5` |
| `as_of` | string (ISO datetime) | yes | Hour bucket start, preferably America/New_York offset (`…T14:00:00-04:00` / `-05:00`). Directory key uses local `YYYY-MM-DD` + `HH`. |
| `orders` | array | yes | May be empty (explicit hold) |
| `thesis` | string | yes | Non-empty short rationale |

### Order object

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `side` | `"buy"` \| `"sell"` | yes | Long-only; sell only reduces existing shared-book position |
| `symbol` | string | yes | US listed equity/ETF ticker |
| `notional_usd` | number | buy: yes | Dollar amount; must be > 0 |
| `qty` | number | sell: yes | Fractional shares; must be > 0 |

Buys use `notional_usd` (not qty). Sells use `qty` (not notional).

## Paths

| Artifact | Path |
|----------|------|
| Agent proposal | `state/hourly/YYYY-MM-DD/HH/A{n}.json` |
| Agent pack (prompt) | `state/hourly/YYYY-MM-DD/HH/A{n}.md` |
| Hour news slice | `state/hourly/YYYY-MM-DD/HH/news.json` |
| Consensus | `state/hourly/YYYY-MM-DD/HH/consensus.json` |
| Validation / settle log | `state/hourly/YYYY-MM-DD/HH/settle.json` |

`HH` is zero-padded America/New_York hour (`10`–`15` during RTH ticks).

## Validation

- Per-agent proposal schema is checked lightly when loading for consensus.
- **Execution** validation is on the **consensus** order list via `scripts/validate_book.py` (shared book caps 15% / 35% / 6), not per-agent daily roster tiers.
- Whole consensus batch reject → hold that hour.

## Fidelity

No invented news/prices; empty proposals OK; do not assume fills before Alpaca confirms. Propose as of the hour cutoff only (`published <` hour start).
