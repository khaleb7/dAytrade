# Hourly input pack — {{AS_OF}}

Paste this into each cloud agent along with `prompts/agent_system.md` and `prompts/{{AGENT_ID}}.md`.

**Mode:** Alpaca paper hourly consensus. You **propose only**. A separate consensus step (≥3/5 majority on `(symbol, side)`, median size) decides what — if anything — is submitted to the shared book. Do **not** assume fills.

## Meta

- `as_of`: {{AS_OF}} (hour bucket start, America/New_York)
- `agent_id`: {{AGENT_ID}}
- Cutoff (UTC): {{CUTOFF_UTC}} — use only news with `published` before this instant
- Shared book caps (execution): cash floor 15%, max name 35%, max 6 positions

## News pack (this hour)

```json
{{NEWS_JSON}}
```

Sources are tagged (`reuters`, `yahoo_finance`, `marketwatch`, `sec_edgar`, `politician_trades`). Do not invent later information.

## Shared book (pre-trade Alpaca mirror — **sizing view**)

```json
{{BOOK_JSON}}
```

`cash_usd` / `equity_usd` here already include `equity_offset_usd` (default **-99000**) so you size against ~**$1000**, not Alpaca’s $100k paper default. `broker_*` fields are the raw account. Shared execution caps: cash floor 15%, max name 35%, max 6 positions — on this sizing equity. Your tier labels guide proposal aggression.

## Shared lessons (anonymized ledger, last ≤20 lines)

```
{{LESSONS_EXCERPT}}
```

## Task

Emit one JSON **proposal** for `as_of={{AS_OF}}` matching `docs/hourly-proposal-schema.md`. If you choose to hold, return `"orders": []` with a thesis explaining why.

```json
{
  "agent_id": "{{AGENT_ID}}",
  "as_of": "{{AS_OF}}",
  "orders": [],
  "thesis": "…"
}
```

Buys: `{"side":"buy","symbol":"VTI","notional_usd":50.0}`  
Sells: `{"side":"sell","symbol":"AAPL","qty":0.15}`

**Fidelity reminder:** no lookahead past this hour’s start; do not invent headlines or prices; do not optimize to look profitable; empty/hold is OK; you propose — consensus executes.
