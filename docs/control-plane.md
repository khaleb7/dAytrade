# DayTrade JS/TS control plane

Hybrid multi-package control plane under `services/`. TypeScript owns the RTH
scheduler, packs, fan-out, consensus, book validate, and Alpaca submit. Python
remains only for news ingest / `build-hour` via `@daytrade/news-bridge`.

> Future Docker: each package is a candidate service. No images in v1 — add a
> `Dockerfile` per package when containerizing.

## Packages

| Package | Role |
|---------|------|
| `@daytrade/shared` | Paths, hour buckets, NYSE calendar, env load, types |
| `@daytrade/news-bridge` | Spawn `scripts/fetch_news.py` ingest + build-hour |
| `@daytrade/book` | Alpaca client, sizing offset (−99000), validate caps |
| `@daytrade/consensus` | Majority ≥3/5 + median size |
| `@daytrade/packs` | Render `A1.md`…`A5.md` from hourly template |
| `@daytrade/fanout` | Cursor SDK **local** agents → `A?.json` (fixtures if no key) |
| `@daytrade/orchestrator` | RTH loop: prep → fanout → settle |

Shared contracts stay file-based:

`state/hourly/YYYY-MM-DD/HH/{news,ready,A*.md,A*.json,consensus,settle,fanout}.json`

## Env (outside store)

```
%USERPROFILE%\.daytrade\alpaca.env
```

Required keys:

- `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` — Alpaca paper
- `CURSOR_API_KEY` — live SDK fan-out (omit → fixture proposals for smoke)

See `services/windows/daytrade.env.example`. Packages refuse env files under the store.

## Install (Node)

```bash
cd services
npm install
npm run build
```

Node 20+ for workspaces; **Node 22.13+** recommended for `@cursor/sdk` local fan-out.
Keep Python 3.9+ on PATH for news-bridge.

## CLI

```bash
# next RTH tick
npm run orchestrator -- --next-tick

# one hour prep (Python news via fixtures)
npm run orchestrator -- --hour 2026-09-25T14 --phase prep --from-fixtures --allow-non-rth

# full hour with fixture proposals (no CURSOR_API_KEY)
npm run orchestrator -- --hour 2026-09-25T14 --phase full --from-fixtures --allow-non-rth

# live loop (Windows Task Scheduler entry)
npm run orchestrator -- --loop --phase prep-then-settle --catch-up

# paper submit opt-in
npm run orchestrator -- --hour … --phase settle --submit
```

Smokes:

```bash
npm run smoke:consensus -- --from-fixtures
npm run smoke:book
npm run smoke:fanout
npm run smoke:prep
```

## Fan-out

For each agent in `state/roster.json`:

```ts
Agent.create({
  apiKey: process.env.CURSOR_API_KEY,
  model: { id: roster.agents[aid].model_id },
  local: { cwd: STORE_ROOT },
})
```

Prompt = system + tier + pack markdown; agent must write only
`state/hourly/.../A{n}.json`. Parallel launch; ~15–20 min timeout.
No cloud runtime in v1. Without `CURSOR_API_KEY`, copies `fixtures/hourly/proposals`.

## Windows

Installer still registers **DayTradeHourlyConsensus**. `Start-HourlyScheduler.ps1`
prefers the Node orchestrator (`services/orchestrator`) and falls back to
`hourly_scheduler.py` if Node/services are missing. Python stays for news.

Details: `docs/windows-scheduler.md`.

## Sizing book

`state/alpaca/config.json` → `equity_offset_usd: -99000` maps ~$100k paper equity
onto ~$1000 sizing for proposals and book caps. Broker fills use real notionals.
