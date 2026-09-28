---
cursor:
  subagentId: "bc-f643c8b2-6459-5b15-8198-ed4ebff3f452"
---

# News cache summary

## Layout (`state/news_cache/`)

| File | Role |
|------|------|
| `items.jsonl` | Append-only rows: `source`, `title`, `url`, `published`, `summary`, `ingested_at`, `ingest_id`, `ingest_via` |
| `gaps.jsonl` | 429s / empty windows / HTTP errors (no spin) |
| `ingest_log.jsonl` | Per-run counters |
| `manifest.json` | Rollup counts + last ingest |

Day packs: `state/news/YYYY-MM-DD.json` (`mode: "cache"`), sliced with `published <` that day’s US RTH open.

Docs: `docs/news-cache.md`, pointer in `docs/project-context.md`.

## How to ingest / build-day

```bash
cd scripts

# Batch historical (default --via gkg = GDELT file dumps on CDN; also pulls House PTRs)
python3 fetch_news.py ingest --backfill-range 2026-06-01 2026-09-27

# Optional extras
python3 fetch_news.py ingest --live-feeds
python3 fetch_news.py ingest --politician-trades          # House PTR only
python3 fetch_news.py ingest --backfill-range … --via doc # DOC API (429-prone)

# Per day — cache only, no upstream
python3 fetch_news.py build-day 2026-06-02 --cache-only
```

Coordinator: **ingest once**, then **`build-day` per as_of**. Never re-hit upstream inside per-day backfill loops. `run_backfill.py --network` already uses cache-only news.

## What was cached (this run)

| Via | Items added | Notes |
|-----|-------------|--------|
| `seed_day_pack` | 27 | Prior `state/news/*.json` |
| `rss` / `edgar` | 59 / 40 | Live feeds (Reuters DNS failed) |
| `gkg` | 2171 | Full range 2026-06-01→09-27; 357/357 files OK |
| `house_ptr` | 915 | House Clerk FD zips 2025+2026, FilingType=P |
| DOC API | 0 useful during hammer; later recovered briefly | Early 429 storm; prefer GKG |

**Totals ~3212 items:** `yahoo_finance` 2232, `politician_trades` 915, `sec_edgar` 41, `marketwatch` 23, `reuters` 1.

Smoke (cache-only, no upstream):

- `2026-06-02.json` — 56 items (`yahoo_finance` 40, `politician_trades` 12, …); 0 lookahead violations
- `2026-06-03.json` — same shape; `--cache-only` on empty dir exits 1

## Politician trades (color)

- Source tag: `politician_trades`
- Upstream: official House Clerk `{year}FD.zip` → PTR rows → PDF links under `ptr-pdfs/{year}/{DocID}.pdf`
- Lookback in day packs: 14 days, cap 12
- **Not** parsed for tickers/size — filing metadata for color only
- Senate eFD: no bulk zip wired (gap)

## Remaining gaps

| Gap | Detail |
|-----|--------|
| Reuters | Almost empty in GKG URL filter; live RSS DNS fail (`feeds.reuters.com`); DOC 429 during first pass |
| MarketWatch / SEC in GKG | Thin vs Yahoo (11 / 0 from GKG; SEC mostly live EDGAR snapshot) |
| DOC API | IP rate-limit after per-day hammering; **do not VPN via Firefox** (not installed; browser VPN would not route Python). Prefer `--via gkg`. `/dev/net/tun` exists but no Mozilla/OpenVPN creds |
| Senate PTR | Not ingested |
| GKG sampling | Only UTC 00/08/12 — some headlines between samples missed |

## VPN note (Firefox)

Firefox / Mozilla VPN are **not** installed in this cloud VM. A browser VPN would not change the egress IP for `fetch_news.py` urllib calls. GKG CDN ingest already bypasses DOC 429; no VPN required for the working path.
