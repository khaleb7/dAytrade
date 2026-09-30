# Hourly input pack — {{AS_OF}}

Paste this into the hourly agent along with `prompts/agent_system.md` and `prompts/{{AGENT_ID}}.md`.

**Mode:** Alpaca paper RTH single-agent (30-minute buckets). You **propose** orders; your valid legs become the book proposal (`min_votes=1`). Shared book caps still gate execution. Do **not** assume fills.

## Meta

- `as_of`: {{AS_OF}} (tick start, America/New_York)
- `agent_id`: {{AGENT_ID}}
- Cutoff (UTC): {{CUTOFF_UTC}} — use only news with `published` before this instant
- Shared book caps (execution): cash floor 8%, max name 45%, max 7 positions
- {{VIX}}

## Market signals (context only)

```
{{MARKET_SIGNALS}}
```

Use for regime context. **Do not** propose VIX, VXX, UVXY, or futures. TLT/USO are ordinary US ETFs and remain allowed only under shared book rules if you choose them.

## News pack (this tick)

```json
{{NEWS_JSON}}
```

Sources are tagged (`reuters`, `yahoo_finance`, `marketwatch`, `sec_edgar`, `politician_trades`). Do not invent later information.

## Shared book (pre-trade Alpaca mirror — **sizing view**)

```json
{{BOOK_JSON}}
```

`cash_usd` / `equity_usd` here already include `equity_offset_usd` (default **-99000**) so you size against ~**$1000**, not Alpaca’s $100k paper default. `broker_*` fields are the raw account. Shared execution caps: cash floor **8%**, max name **45%**, max **7** positions — on this sizing equity.

## Prior day-end analysis (for continuity)

```
{{DAY_END_ANALYSIS}}
```

Carry forward themes and risk notes; do not invent fills that the analysis does not show.

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

**Fidelity reminder:** no lookahead past this tick’s start; do not invent headlines or prices; do not optimize to look profitable; empty/hold is OK; you propose — settle validates and submits.
