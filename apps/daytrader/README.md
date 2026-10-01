# Daytrader

One CronJob tick. It reads Newstracker and the Alpaca paper account, asks a local Cursor agent for a proposal, checks caps, and submits long-only paper orders. Sells only close or reduce a position.

The image is a Node 22 build followed by `gcr.io/distroless/nodejs22-debian12`. The entrypoint is `/nodejs/bin/node dist/cli.js`. The agent writes under `DAYTRADE_WORK` (an emptyDir at `/work` in the cluster).

## When it trades

The CronJob schedule is `0,30 9-16 * * 1-5` in `America/New_York`, with `concurrencyPolicy: Forbid`. The process exits 0 unless the clock is an NYSE regular-session tick from 09:30 through 15:30, snapped to `:00` or `:30`. Weekends, the holiday list in `src/calendar.ts`, and the 09:00 and 16:00 fires exit 0. The first live tick of a session is 09:30.

`activeDeadlineSeconds` is 1500. `backoffLimit` is 1.

## Tick

1. `GET` Newstracker `/v1/context` at the tick cutoff. Articles published at or after the cutoff are excluded.
2. `GET` Alpaca paper `/v2/account` and `/v2/positions`. Market data stays on Newstracker; this process does not call `data.alpaca.markets`.
3. Size the book with `equity_offset_usd`, default `-99000`, so a ~$100,000 paper account is treated as about $1,000.
4. Run one local Cursor agent (`Agent.create`, model `grok-4.7` unless `DAYTRADE_MODEL` is set) with the prompts in `prompts/`. It may write `A1.json`.
5. Reject the proposal if it breaks the caps: 8% cash floor, 45% in one name, 7 positions. Signal-only symbols such as VIX are blocked.
6. `POST /v2/orders` only when orders remain and `DAYTRADE_DRY_RUN` is not `1`. Buys use notional. Sells use quantity.

The agent wait defaults to 20 minutes (`DAYTRADE_PROPOSAL_WAIT_MINUTES`).

## Environment

| Name | Default |
| --- | --- |
| `NEWSTRACKER_URL` | required |
| `DAYTRADE_WORK` | `/work` |
| `DAYTRADE_MODEL` | `grok-4.7` |
| `DAYTRADE_PROPOSAL_WAIT_MINUTES` | `20` |
| `DAYTRADE_DRY_RUN` | unset; `1` skips submit |
| `APCA_API_KEY_ID` | required to reconcile and submit |
| `APCA_API_SECRET_KEY` | required to reconcile and submit |
| `APCA_API_BASE_URL` | `https://paper-api.alpaca.markets` |
| `CURSOR_API_KEY` | required for the agent |
| `DAYTRADE_DISCORD_WEBHOOK_URL` | unset; startup and decision pings are skipped |

Discord is optional. The process still posts a startup message on every invocation, including ticks that exit before trading. Hold, reject, dry-run, and submit each post as well. HTTP errors do not fail the tick.

## Build

From the repository root:

```sh
nerdctl build -f apps/daytrader/Dockerfile -t daytrader:latest .
```
