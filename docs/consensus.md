# Hourly consensus rules

Five agents (A1–A5) each return an **hourly proposal**. Consensus builds one shared order list for the Alpaca paper book. Agents propose only; **consensus executes**.

## Majority (≥3/5)

1. Group every proposed leg by `(symbol, side)` (`side` ∈ `buy` | `sell`).
2. A leg enters the consensus order list only if **≥3 agents** proposed that exact `(symbol, side)`.
3. Agents with `"orders": []` (explicit holds) do **not** block consensus on other legs and do **not** count toward the 3 for any leg.
4. If no leg reaches 3 votes → no trade that hour (log proposals + `"no_consensus": true`).

## Size (median)

Among agents who proposed the winning `(symbol, side)`:

| Side | Size field | Aggregation |
|------|------------|-------------|
| buy | `notional_usd` | **median** of agreeing agents’ notionals |
| sell | `qty` | **median** of agreeing agents’ qtys; then **scale down** to held qty if median exceeds book |

Median of an even count uses the average of the two middle values (standard statistical median). Round buys to cents; sells keep reasonable fractional precision (≤6 dp).

## Shared book caps (balanced-tier defaults)

Validated by `scripts/validate_book.py` against the **shared** Alpaca mirror (`state/book/portfolio.json`), not per-agent roster tiers:

| Cap | Value |
|-----|-------|
| Cash floor | **15%** of post-trade equity |
| Max single name | **35%** of post-trade equity |
| Max positions | **6** |

Also: long-only, no shorting, buys affordable from cash, US equity/ETF tickers only. **Whole-batch reject** on any failure → hold (no Alpaca submit).

### Paper equity offset ($100k → ~$1000)

Alpaca paper defaults to **$100,000**. Config `state/alpaca/config.json` → `equity_offset_usd: -99000` shifts cash/equity for **agent packs and book-cap validation** only (`sizing_book()`). Broker account numbers stay truthful in `state/book/portfolio.json`; submitted order notionals/qtys are unchanged.

## Empty holds

`"orders": []` with a non-empty thesis is valid. Holds neither vote for nor against other symbols.

## Output

`scripts/consensus.py` writes `state/hourly/YYYY-MM-DD/HH/consensus.json`:

```json
{
  "as_of": "2026-09-25T14:00:00-04:00",
  "orders": [
    {"side": "buy", "symbol": "VTI", "notional_usd": 50.0, "votes": 3, "agents": ["A2", "A3", "A4"]}
  ],
  "rejected_legs": [],
  "no_consensus": false,
  "proposals_loaded": ["A1", "A2", "A3", "A4", "A5"]
}
```

## Examples

**Majority buy.** A1 hold; A2/A3/A4 buy VTI at 40/50/60; A5 buys SPY. Consensus: buy VTI at median **50**; SPY dropped (1 vote).

**Holds do not block.** Three agents buy QQQ; two hold. Consensus includes QQQ.

**Caps reject.** Consensus would put cash under 15% → `validate_book` fails → no submit.
