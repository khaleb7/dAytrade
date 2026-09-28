# News cache — batch ingest, then day packs

Avoids GDELT/RSS **429** storms during backfill by pulling upstream **once** into a durable local cache, then slicing each trading day’s pack from cache only (no lookahead past US RTH open).

## Layout (`state/news_cache/`)

| Path | Role |
|------|------|
| `items.jsonl` | Append-only articles: `source`, `title`, `url`, `published`, `summary`, `ingested_at`, `ingest_id`, `ingest_via` |
| `gaps.jsonl` | Recorded misses: HTTP 429/errors, empty windows, `maxrecords` caps |
| `ingest_log.jsonl` | One row per ingest run (counts, range, chunk size) |
| `manifest.json` | Rollup: item counts by source, published min/max, layout note |

Day packs remain at `state/news/YYYY-MM-DD.json` (same schema as before; `mode` is `"cache"`).

Hour packs (Alpaca consensus) write to `state/hourly/YYYY-MM-DD/HH/news.json` from the **same** cache.

## Commands

From `scripts/`:

```bash
# 1) Batch ingest via GDELT GKG file dumps (CDN; default — avoids DOC API 429)
python fetch_news.py ingest --backfill-range 2026-06-01 2026-09-27

# Optional: DOC API instead (often 429 under load), or seed + live RSS/EDGAR
python fetch_news.py ingest --backfill-range 2026-06-01 2026-09-27 --via doc
python fetch_news.py ingest --seed-day-packs --live-feeds
# Politician trades only (House STOCK Act PTR index)
python fetch_news.py ingest --politician-trades

# 2) Build one day pack from cache only (no upstream calls)
python fetch_news.py build-day 2026-06-02 --cache-only

# 3) Hourly tick (Alpaca mode): live ingest once, then cache-only hour slice
python fetch_news.py ingest --live-feeds
python fetch_news.py build-hour 2026-09-25T14
# → state/hourly/2026-09-25/14/news.json  (cutoff = that hour’s start ET)
```

Coordinator backfill loop should **never** call per-day live/GDELT fetches. Order of operations:

1. `ingest --backfill-range FROM TO` (once, or when extending the range; default `--via gkg`)
2. For each `as_of`: `build-day YYYY-MM-DD` → writes `state/news/YYYY-MM-DD.json`
3. Fan-out agents / settle as usual

Hourly consensus (`run_hourly.py`): `ingest --live-feeds` (optional `--skip-ingest`) then `build-hour` from cache only — never per-agent live hammering / DOC.

`run_backfill.py --network` uses **cache-only** news builds; if the cache is empty it falls back to fixtures and prints a warning.

## No-lookahead rule

`build-day` keeps items with `published < cutoff_utc` where cutoff is that day’s US RTH open (`≈13:30Z` / `09:30 America/New_York`). Items on or after open are dropped. News lookback is ~2 calendar days before `as_of`; `politician_trades` lookback is ~14 days (capped at 12 items/day).

`build-hour` keeps items with `published <` that hour’s start (America/New_York by default). Same lookback windows; output under `state/hourly/…/news.json`.

## Sources

| Source tag | Upstream |
|------------|----------|
| `reuters` | GKG dumps matching `reuters.com` URLs (+ live RSS when `--live-feeds`) |
| `yahoo_finance` | GKG `finance.yahoo.com` (+ Yahoo RSS) |
| `marketwatch` | GKG `marketwatch.com` (+ MW RSS) |
| `sec_edgar` | GKG `sec.gov` (+ SEC EDGAR Atom) |
| `politician_trades` | US House STOCK Act **Periodic Transaction Reports** from official Clerk FD zips (`disclosures-clerk.house.gov`). Color/context only — filing metadata + PDF link, not parsed tickers. |

**Default ingest** (`--via gkg`) samples GDELT **GKG 15-min zip dumps** from `data.gdeltproject.org` at UTC hours 00/08/12 each calendar day — batch file pulls, not per-day DOC queries. Optional `--via doc` uses the DOC ArtList API with **14-day chunks**, `maxrecords=250`, and limited 429 backoff (record gap, no spin).

`--backfill-range` also pulls House PTR indexes (`--politician-trades`; skip with `--skip-politician-trades`). Senate eFD has no public bulk zip in this pipeline yet.

## Gaps

Inspect `state/news_cache/gaps.jsonl` and the summary in `internal/news-cache-summary.md`. Thin or empty day packs are valid; agents may hold.
