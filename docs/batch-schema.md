# Trade batch schema

Agents return exactly one JSON batch per trading day. Settlement rejects the **entire** batch on any validation failure (agent holds).

## Schema

```json
{
  "agent_id": "A3",
  "as_of": "2026-06-02",
  "orders": [
    {"side": "buy", "symbol": "VTI", "notional_usd": 20.0},
    {"side": "sell", "symbol": "AAPL", "qty": 0.15}
  ],
  "thesis": "Short rationale for the batch."
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `agent_id` | string | yes | One of `A1`…`A5` |
| `as_of` | string (ISO date) | yes | Trading day being decided; must match sim date |
| `orders` | array | yes | May be empty (explicit hold) |
| `thesis` | string | yes | Non-empty short rationale |

### Order object

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `side` | `"buy"` \| `"sell"` | yes | Long-only; sell only reduces existing position |
| `symbol` | string | yes | US listed equity/ETF ticker (A–Z, digits, `.` / `-` allowed for class shares) |
| `notional_usd` | number | buy: yes | Dollar amount to spend at open; must be > 0 |
| `qty` | number | sell: yes | Fractional shares to sell; must be > 0 and ≤ held qty |

Buys use `notional_usd` (not qty). Sells use `qty` (not notional). Mixing the wrong sizing field is a reject.

## Validation rules (whole-batch reject)

Enforced by `scripts/validate_batch.py` against `state/roster.json` and the agent’s pre-trade portfolio + that day’s open prices:

1. Schema / types / `agent_id` / `as_of` match.
2. One batch per agent per day; orders list only.
3. Symbols look like US equity/ETF tickers; no options/crypto/OTC markers.
4. No shorting: sell qty ≤ held; no sell of unknown symbol.
5. After simulated fills at open:
   - Cash ≥ tier `cash_floor_pct` of post-trade equity.
   - Each position market value ≤ `max_single_name_pct` of equity.
   - Number of open positions ≤ `max_positions`.
6. Buys must be affordable from cash (no margin).
7. Market must provide an open price for every symbol traded that day.

On reject: no fills; portfolio unchanged; journal records the rejection reason.
