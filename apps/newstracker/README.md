# Newstracker

Always-on Python poller. One source per cycle, then sleep. It writes SQLite and serves a read API. It does not trade.

Image: `gcr.io/distroless/python3-debian12`, standard library only. The process runs as uid 65532.

## What it fetches

News, one feed at a time:

- Reuters business RSS
- Yahoo Finance RSS
- MarketWatch top stories RSS
- SEC EDGAR current 8-K Atom feed

Alpaca market data, one symbol at a time, from `https://data.alpaca.markets` (not the paper trading API). Each symbol turn requests the last three daily bars and the last five 1-minute bars, feed `iex`:

```
GET /v2/stocks/{symbol}/bars?timeframe=1Day&limit=3&feed=iex
GET /v2/stocks/{symbol}/bars?timeframe=1Min&limit=5&feed=iex
```

When an EDGAR source is due, it is taken before any RSS feed or bar symbol.

Default symbols: `SPY, QQQ, IWM, VTI, TLT, USO, AAPL, MSFT, NVDA, AMZN, GOOGL, META`. If either Alpaca key is unset, bar sources are skipped and news still runs.

Each request is a single attempt. The next eligible time is stored on the source:

| Outcome | Wait |
| --- | --- |
| Bar success | 180s |
| RSS or EDGAR success | 300s |
| Other error | 300s |
| HTTP 429 or a rate-limit body | 900s, or `Retry-After` if longer |

The cycle sleep after every attempt defaults to 60s. Sources share one queue, so a bar and a feed are never fetched in the same cycle.

## Store

SQLite at `NEWSTRACKER_DB` (default `/data/newstracker.db`), WAL mode.

- `articles` deduped by URL, otherwise `source|title|published`
- `bars` upserted on `(symbol, ts)` for the 1-minute prints
- `sessions` upserted on `(symbol, day)` for the daily open, high, low, and close
- `sources` holds `next_eligible_at`, the last error, and the RSS etag

## HTTP

| Path | Behavior |
| --- | --- |
| `GET /health` | `ok`, article count, bar count, source count |
| `GET /v1/context?as_of=` | Articles with `published < as_of`, at most 40 per source. Optional `lookback_days` is clamped to 1–14 and defaults to 2. Optional `since` raises the start of that window. Bars are the latest 1-minute row per symbol with `ts < as_of`. `quotes` adds session open, high, low, last, and the prior session close. |

Kubernetes names the Service `newstracker`, which would inject `NEWSTRACKER_PORT=tcp://<ip>:8080`. The Deployment sets `enableServiceLinks: false` and `NEWSTRACKER_PORT=8080` so the listen port stays numeric.

## Environment

| Name | Default |
| --- | --- |
| `NEWSTRACKER_DB` | `/data/newstracker.db` |
| `NEWSTRACKER_BIND` | `0.0.0.0` |
| `NEWSTRACKER_PORT` | `8080` |
| `NEWSTRACKER_CYCLE_SLEEP` | `60` |
| `NEWSTRACKER_FEED_INTERVAL` | `300` |
| `NEWSTRACKER_BAR_INTERVAL` | `180` |
| `NEWSTRACKER_ERROR_BACKOFF` | `300` |
| `NEWSTRACKER_RATE_LIMIT_BACKOFF` | `900` |
| `NEWSTRACKER_SYMBOLS` | the default list above |
| `NEWSTRACKER_ALPACA_DATA_URL` | `https://data.alpaca.markets` |
| `NEWSTRACKER_ALPACA_FEED` | `iex` |
| `APCA_API_KEY_ID` | unset |
| `APCA_API_SECRET_KEY` | unset |
| `DAYTRADE_DISCORD_WEBHOOK_URL` | unset; startup ping is skipped |

## Build

From the repository root:

```sh
nerdctl build -f apps/newstracker/Dockerfile -t newstracker:latest .
```
