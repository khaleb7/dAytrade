# Daily input pack — {{DATE}}

Paste this into each cloud agent along with `prompts/agent_system.md` and `prompts/{{AGENT_ID}}.md`.

## Meta

- `as_of`: {{DATE}}
- `agent_id`: {{AGENT_ID}}
- US RTH open cutoff (UTC): {{CUTOFF_UTC}}

## News pack

```json
{{NEWS_JSON}}
```

Sources are tagged (`reuters`, `yahoo_finance`, `marketwatch`, `sec_edgar`). All items are intended to be **before** the open — do not invent later information.

## Your portfolio (pre-trade)

```json
{{PORTFOLIO_JSON}}
```

## Your recent journal (last ≤5 sessions)

```json
{{JOURNAL_EXCERPTS}}
```

## Shared lessons (anonymized ledger, last ≤20 lines)

```
{{LESSONS_EXCERPT}}
```

## Task

Emit one JSON trade batch for `as_of={{DATE}}` that respects your tier rules after fills at open. If you choose to hold, return `"orders": []` with a thesis explaining why.

**Fidelity reminder:** no lookahead past US RTH open; do not invent headlines or prices; do not optimize to look profitable; empty/hold is OK; aggressive sizing still must pass the whole-batch validator.
