# Daytrader

One CronJob tick. It reads Newstracker and the Alpaca paper account, builds a pre-declared order batch, and lets a local Cursor agent accept or reject that batch. Caps still apply. Sells only close or reduce a position. The agent does not add symbols.

The image is a Node 22 build followed by `gcr.io/distroless/nodejs22-debian12`. The entrypoint is `/nodejs/bin/node dist/cli.js`. The agent writes under `DAYTRADE_WORK` (an emptyDir at `/work` in the cluster).

## When it trades

The CronJob schedule is `0,30 9-16 * * 1-5` in `America/New_York`, with `concurrencyPolicy: Forbid`. The process exits 0 unless the clock is an NYSE regular-session tick from 09:30 through 15:30, snapped to `:00` or `:30`. Weekends, the holiday list in `src/calendar.ts`, and the 09:00 and 16:00 fires exit 0. The first live tick of a session is 09:30.

`activeDeadlineSeconds` is 1500. `backoffLimit` is 1.

## Tick

1. `GET` Newstracker `/v1/context` at the tick cutoff, with `since` set to the previous tick. Articles in the pack were published inside that window.
2. `GET` Alpaca paper `/v2/account` and `/v2/positions`. Market data stays on Newstracker; this process does not call `data.alpaca.markets`.
3. Size the book with `equity_offset_usd`, default `-99000`, so a ~$100,000 paper account is treated as about $1,000.
4. Score the previous tick against doing nothing. Excess return is the simulated rule batch minus the untouched book, after `DAYTRADE_SPREAD_BPS` (default 5) on traded notional. The row is appended to `DAYTRADE_SCOREBOARD`.
5. Build the rule batch. The passive core is `DAYTRADE_CORE_SYMBOL` at `DAYTRADE_CORE_WEIGHT` (default VTI at 25%). Rebalance when the weight is outside `DAYTRADE_REBALANCE_BAND` (default 5 percentage points). A name still held that is down `DAYTRADE_GAP_CUT` (default 3%) from the prior close is sold, and that symbol is not bought back on the same tick. A buy that would break the 8% cash floor is cut or dropped.
6. Run one local Cursor agent (`Agent.create`, model `grok-4.7` unless `DAYTRADE_MODEL` is set). It writes `accept` or `reject`. A reject clears the batch. A missing or failed verdict leaves the rules in place.
7. Reject the batch if it breaks the caps: 8% cash floor, 45% in one name, 7 positions. Signal-only symbols such as VIX are blocked.
8. `POST /v2/orders` only when orders remain, `DAYTRADE_DRY_RUN` is not `1`, and the scoreboard has at least `DAYTRADE_MIN_SCORED_SESSIONS` distinct sessions (default 20). Until then the tick is a dry run. Buys use notional. Sells use quantity.

The agent wait defaults to 20 minutes (`DAYTRADE_PROPOSAL_WAIT_MINUTES`).

## Environment

| Name | Default |
| --- | --- |
| `NEWSTRACKER_URL` | required |
| `DAYTRADE_WORK` | `/work` |
| `DAYTRADE_MODEL` | `grok-4.7` |
| `DAYTRADE_PROPOSAL_WAIT_MINUTES` | `20` |
| `DAYTRADE_DRY_RUN` | unset; `1` skips submit. Submit also stays off until enough sessions are scored |
| `DAYTRADE_SCOREBOARD` | `/data/scoreboard.json` |
| `DAYTRADE_CORE_SYMBOL` | `VTI` |
| `DAYTRADE_CORE_WEIGHT` | `0.25` |
| `DAYTRADE_REBALANCE_BAND` | `0.05` |
| `DAYTRADE_GAP_CUT` | `0.03` |
| `DAYTRADE_SPREAD_BPS` | `5` |
| `DAYTRADE_MIN_SCORED_SESSIONS` | `20` |
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
