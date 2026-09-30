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
| `@daytrade/book` | Alpaca client, sizing offset (−99000), validate caps **8%/45%/7** |
| `@daytrade/consensus` | Single-agent settle orders (`min_votes=1`) |
| `@daytrade/packs` | Render `A1.md` from hourly template (+ market signals) |
| `@daytrade/fanout` | Cursor SDK **local** agent → `A1.json` (fixtures if no key) |
| `@daytrade/orchestrator` | RTH loop: prep → fanout → settle |

Shared contracts stay file-based:

`state/hourly/YYYY-MM-DD/HHMM/{news,ready,A*.md,A*.json,consensus,settle,fanout}.json`

Half-hour slots use `HHMM` (`0930`, `1000`, …, `1530`). Legacy hour-only dirs (`14`) still resolve for reads.

Day-end: `state/daily/YYYY-MM-DD/analysis.json` (+ `analysis.md`) — written after the **15:30** tick; packs inject the latest prior analysis into fan-out prompts.

Market signals (VIX / Treasury yields / oil): `state/signals/latest.json` + per-tick `signals.json` — **context only**; see `internal/market-signals-vix-bonds-oil.md`.

## Env (outside store)

```
%USERPROFILE%\.daytrade\alpaca.env
```

Required keys:

- `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` — Alpaca paper
- `CURSOR_API_KEY` — live SDK fan-out (omit → fixture proposals for smoke)

Optional:

- `DAYTRADE_DISCORD_WEBHOOK_URL` — Discord embeds for tick start/end, issues, consensus/submit, day-end (soft-fail; never blocks trading)
- `DAYTRADE_PROPOSAL_WAIT_MINUTES` — fan-out / proposal wait (default **20** on 30m ticks)

See `services/windows/daytrade.env.example` and `scripts/windows/alpaca.env.example`. Packages refuse env files under the store.

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

# live loop (Windows Task Scheduler) — 30m RTH ticks, paper submit ON
npm run orchestrator -- --loop --phase prep-then-settle --catch-up

# day-end analysis only
npm run orchestrator -- --hour 2026-09-28 --phase day-end

# opt out of paper orders
npm run orchestrator -- --hour 2026-09-28T14:30 --phase settle --dry-run
```

Smokes:

```bash
npm run smoke:consensus -- --from-fixtures
npm run smoke:book
npm run smoke:fanout
npm run smoke:prep
```

## Fan-out

For each agent in `state/roster.json` (single **A1** / `grok-4.7`):

```ts
Agent.create({
  apiKey: process.env.CURSOR_API_KEY,
  model: { id: roster.agents[aid].model_id },
  local: { cwd: STORE_ROOT },
})
```

Prompt = system + tier + pack markdown; agent must write only
`state/hourly/.../A1.json`. Single local agent; **20 min** timeout default.
No cloud runtime in v1. Without `CURSOR_API_KEY`, copies `fixtures/hourly/proposals`.

## Windows

Installer still registers **DayTradeHourlyConsensus**. `Start-HourlyScheduler.ps1`
prefers the Node orchestrator (`services/orchestrator`) and falls back to
`hourly_scheduler.py` if Node/services are missing. Python stays for news.

Details: `docs/windows-scheduler.md`.

## Sizing book

`state/alpaca/config.json` → `equity_offset_usd: -99000` maps ~$100k paper equity
onto ~$1000 sizing for proposals and book caps. Broker fills use real notionals.
