# DayTrade — project context

Cursor-orchestrated investment system with two modes:

1. **Daily backfill / live sim** (paused): five risk-tier agents each place one pre-market trade batch per US trading day on separate $100 books.
2. **Alpaca paper hourly consensus** (active build): same A1–A5 roster proposes each RTH hour; **majority consensus** drives one shared **$1000** Alpaca paper book.

## Goals

- Compare risk-tier proposal behavior across five LLM-backed agents on shared news.
- Daily mode: backfill from **2026-06-01** (paused unless resumed separately).
- Hourly mode: paper trade via Alpaca with fidelity over profits; seed lessons from the daily backfill ledger.
- Keep all simulator / paper artifacts in this Project store (not the Kubespray `/workspace` checkout).

## Locked rules (shared universe)

| Rule | Value |
|------|-------|
| Universe | US equities & ETFs only |
| Direction | Long-only; fractional shares OK |
| Forbidden | Options, crypto, OTC, shorts |
| News | Reuters, Yahoo Finance, MarketWatch (+ SEC EDGAR) + House STOCK Act PTR; **ingest → `state/news_cache/`**, then cache-only packs; no DOC hammer. See [`news-cache.md`](./news-cache.md). |
| Runtime | Cursor Project + cloud agents only |
| Credentials | Alpaca keys via env only — **never** in the store |

## Fidelity rules (non-negotiable)

**Fidelity over profits.** Losses, empty books, and rejected batches are acceptable. Do not game the system.

1. **No lookahead.** Daily: before US RTH open. Hourly: before that hour’s start. News packs filter `published < cutoff`.
2. **No invention.** Do not fabricate headlines, tickers, prices, filings, or catalysts.
3. **No profit-seeking bias.** Do not optimize to look profitable in hindsight.
4. **Empty / hold is OK.** `"orders": []` with a real thesis is valid.
5. **Caps still enforced.** Daily: per-agent roster. Hourly consensus: shared book 15% cash / 35% max name / 6 positions — breaches **reject the whole batch**.
6. **No cross-agent leakage.** Packs must not reveal other agents’ IDs, portfolios, or theses — only anonymized ledger lines.

---

## Mode A — Daily backfill / live sim (paused)

| Rule | Value |
|------|-------|
| Capital | $100 per agent at start |
| Sim start | 2026-06-01 |
| Prices | Yahoo Finance daily OHLCV (`yfinance`); fill at **open**, mark at **close** |
| Batches | One per agent per day; invalid → **reject whole batch** (hold) |

### Agent roster (proposal tiers; daily capital rules)

| Agent | Risk | Cash floor | Max name | Max positions | Model |
|-------|------|------------|----------|---------------|-------|
| A1 | Very conservative | 40% | 15% | 3 | `gpt-5.6-sol-medium` |
| A2 | Conservative | 25% | 25% | 4 | `claude-sonnet-5-thinking-medium` |
| A3 | Balanced | 15% | 35% | 6 | `gemini-3.8-flash-medium` |
| A4 | Aggressive | 5% | 50% | 8 | `claude-opus-5-thinking-medium` |
| A5 | Speculative | 0% | 80% | 10 | `grok-4.7-medium` |

Authoritative machine-readable copy: `state/roster.json`.

### Daily store layout

- `state/sim-meta.json` — `sim_date`, `mode` (`backfill` \| `live`)
- `state/agents/A1…A5/portfolio.json` + `journal/`
- `state/lessons/ledger.jsonl` — anonymized cross-agent lessons
- `state/news/YYYY-MM-DD.json`, `state/market/YYYY-MM-DD.json`
- `state/batches/YYYY-MM-DD/A*.json`
- Batch schema: [`batch-schema.md`](./batch-schema.md)

### Daily cycle

1. Pre-market pack (news + portfolios + lessons)
2. Fan-out five cloud agents — see [`orchestration.md`](./orchestration.md)
3. Validate (whole-batch reject)
4. Settle at open; EOD mark at close; journals + ledger
5. Advance to next NYSE trading day

### News ingest vs day packs

```bash
cd scripts
python fetch_news.py ingest --backfill-range 2026-06-01 2026-09-27
python fetch_news.py build-day 2026-06-02 --cache-only
```

Do **not** re-hit GDELT/RSS inside per-day backfill loops. Details: [`news-cache.md`](./news-cache.md).

### Smoke (daily, no LLMs)

```bash
cd scripts
python run_backfill.py --dry-run --max-days 1
```

---

## Mode B — Alpaca paper hourly consensus

Plan: [`alpaca-hourly-plan.md`](./alpaca-hourly-plan.md). Rules: [`consensus.md`](./consensus.md). Schema: [`hourly-proposal-schema.md`](./hourly-proposal-schema.md).

| Decision | Value |
|----------|-------|
| Broker | Alpaca **paper** only |
| Book | One shared portfolio, **$1000** start |
| Agents | Same A1–A5 roster / models (risk tiers guide **proposals** only) |
| Cadence | Hourly US RTH on the hour: **10:00–15:00 America/New_York** |
| Trigger | Majority **≥3/5** on `(symbol, side)`; median size |
| Book caps | Cash **15%**, max name **35%**, max **6** positions (on **sizing** equity) |
| Paper sizing | `equity_offset_usd: -99000` in `state/alpaca/config.json` — packs + validate treat $100k paper as ~$1000; broker submits use proposal notionals as-is |
| News | Ingest live feeds into cache each tick, then `build-hour` from cache only |

### Hourly store layout

- `state/alpaca/config.json` — paper flag, base URL, target equity (no secrets)
- `state/book/portfolio.json` — mirrored Alpaca positions + cash
- `state/hourly/YYYY-MM-DD/HH/` — news, packs, proposals, consensus, settle
- `scripts/alpaca_client.py`, `consensus.py`, `validate_book.py`, `run_hourly.py`, `build_hourly_packs.py`

### Hourly cycle (summary)

1. Ingest news → cache (`fetch_news.py ingest --live-feeds`)
2. Build hour pack from cache (`build-hour`)
3. Fan-out A1–A5 (propose only)
4. Consensus → validate book caps → Alpaca submit (or `--dry-run`)
5. Journal + lessons

```bash
cd scripts
python run_hourly.py --hour 2026-09-25T14 --dry-run --skip-ingest --from-fixtures
```

Secrets: `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, optional `APCA_API_BASE_URL` (default paper). Never write keys into the store.

Windows long-running ticks: [`windows-scheduler.md`](./windows-scheduler.md).

### Orchestration

See [`orchestration.md`](./orchestration.md) for daily fan-out **and** hourly consensus + Alpaca submit playbook.
