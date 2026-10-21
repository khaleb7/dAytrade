# Daytrader

One CronJob tick. With `DAYTRADE_MODE=scalp` it day-trades the Newstracker watchlist. Without that mode it builds the 45% QQQ / 40% VTI sleeve and submits that batch. Caps still apply. Sells only close or reduce a position.

The image is a Node 22 build followed by `gcr.io/distroless/nodejs22-debian12`. The entrypoint is `/nodejs/bin/node dist/cli.js`. Scratch files go under `DAYTRADE_WORK` (an emptyDir at `/work` in the cluster).

## When it trades

The CronJob schedule is `0,30,55 9-15 * * 1-5` in `America/New_York`, with `concurrencyPolicy: Forbid`. The process exits 0 unless the clock is an NYSE regular-session tick from 09:30 through 15:30, snapped to `:00` or `:30`. Weekends, the holiday list in `src/calendar.ts`, and the 09:00 and `:55` fires other than the scalp close exit 0. The first tick of a session is 09:30.

`activeDeadlineSeconds` is 1500. `backoffLimit` is 1.

## Sleeve tick

This path runs when `DAYTRADE_MODE` is not `scalp`.

1. `GET` Newstracker `/v1/context` at the tick cutoff, with `since` set to the previous tick. Articles in the pack were published inside that window.
2. `GET` Alpaca `/v2/account` and `/v2/positions` on `APCA_API_BASE_URL`. Market data stays on Newstracker; this process does not call `data.alpaca.markets`.
3. Size the book with `DAYTRADE_EQUITY_OFFSET_USD`. The code default is `-99000`, so a ~$100,000 paper account is treated as about $1,000. The cluster CronJob sets the offset to `0` and the base URL to `https://api.alpaca.markets`, so the cash account is sized as it is.
4. Score the previous tick against doing nothing. Excess return is the simulated rule batch minus the untouched book, after `DAYTRADE_SPREAD_BPS` (default 5) on traded notional. The row is appended to `DAYTRADE_SCOREBOARD`.
5. Build the rule batch. The growth sleeve is `DAYTRADE_TARGETS` (default `QQQ:0.45,VTI:0.40`, so about 15% cash). Each name is capped at 45%, and the weights are scaled down if they would break the 8% cash floor. Rebalance when a target is outside `DAYTRADE_REBALANCE_BAND` (default 5 percentage points). A down close does not sell. `DAYTRADE_GAP_CUT` defaults to `0`, which leaves that path off; a value above zero sells a held name down at least that far from the prior close and skips buying it back on the same tick. A buy that would break the cash floor is cut or dropped. QQQ is bought before VTI when cash is short. `DAYTRADE_BREAKER` defaults to `0.07`. A target whose session low or last trades at or under that far below the session open is sold in full. It stays out until a later session closes up: the 15:30 tick if the last is above the prior close, or the next morning if the prior session closed up. A day stop rests at the same line when the broker accepts it. A rejected stop leaves the half-hour market sell as the backup. Set the breaker to `0` to turn it off.
6. Reject the batch if it breaks the caps: 8% cash floor, 45% in one name, 7 positions. Signal-only symbols such as VIX are blocked.
7. `POST /v2/orders` only when orders remain, `DAYTRADE_DRY_RUN` is not `1`, and the scoreboard has at least `DAYTRADE_MIN_SCORED_SESSIONS` distinct sessions (default 20). Until then the tick is a dry run. Buys use notional. Sells use quantity. The sleeve does not call a model.

## Scalp

`DAYTRADE_MODE=scalp` is the daytrade. The 45% QQQ / 40% VTI sleeve remains in the code for a buy-and-stay book and runs only when that mode is unset. The scalp buys from the Newstracker symbol list except VTI. That list is the original broad ETFs and mega-caps, plus DIA, XLF, XLE, GLD, TSLA, AVGO, AMD, JPM, V, LLY, COST, XOM, WMT, and NFLX. Shares already held when the mode starts stay reserved. New buys start at 10:30 ET, after the opening rush. The 15:55 tick market-sells every scalp still held, so a loser is not carried into the next open. The 09:30 and 10:00 ticks sell anything that close missed. The reserved lot is not sold. A name qualifies on the stored print when its last price is above both the session open and the prior close. Before any buy, a fresh IEX trade has to still be above both, and either no more than 0.40% above the session open or no more than 0.40% above a real print from 30 minutes earlier. The half-hour path is also capped at 1.25% above the open. A name with a sell fill already today is not bought again. A sell today, or a stop on the same tick, does not open a different name. A name already held can still take another clip. The clip reserved until 13:00 can add to a name already held, and it does not open a new name. At most two new names are taken on a tick, headlines first. Each clip is 15% of equity, and a name that still qualifies can take more clips, up to 45% of equity. One clip stays unspent until the 13:00 tick. The 15:00 and 15:30 ticks do not buy when the next day is a weekend or an NYSE holiday. A scalp down 0.5% from its average cost is sold on the next tick, and only from a fresh IEX trade on that tick. A missing trade leaves the position. A name already through 45% because the price moved does not block a stop of a different name. After a fill, a day OCO rests a +1% limit and a 0.5% stop. If that order is rejected, the +1% day limit remains and the half-hour stop is the backup. The agent veto and the 20-session gate are not used. Ticks append to `DAYTRADE_SCALP_SCOREBOARD` (`/data/scoreboard-scalp.json`).

## Environment

| Name | Default |
| --- | --- |
| `NEWSTRACKER_URL` | required |
| `DAYTRADE_WORK` | `/work` |
| `DAYTRADE_MODEL` | `grok-4.7` |
| `DAYTRADE_PROPOSAL_WAIT_MINUTES` | `20` |
| `DAYTRADE_DRY_RUN` | unset; `1` skips submit. Submit also stays off until enough sessions are scored |
| `DAYTRADE_SCOREBOARD` | `/data/scoreboard.json` |
| `DAYTRADE_TARGETS` | `QQQ:0.45,VTI:0.40` |
| `DAYTRADE_REBALANCE_BAND` | `0.05` |
| `DAYTRADE_GAP_CUT` | `0` (off; a positive fraction sells a held name down at least that far from the prior close) |
| `DAYTRADE_BREAKER` | `0.07` (sell a sleeve name 7% under its session open; `0` turns it off) |
| `DAYTRADE_SPREAD_BPS` | `5` |
| `DAYTRADE_MIN_SCORED_SESSIONS` | `20` |
| `DAYTRADE_MODE` | unset runs the QQQ/VTI sleeve; `scalp` is the daytrade |
| `DAYTRADE_SCALP_SCOREBOARD` | `/data/scoreboard-scalp.json` |
| `DAYTRADE_SCALP_RESERVE` | `/data/scalp-reserve.json` |
| `APCA_API_KEY_ID` | required to reconcile and submit |
| `APCA_API_SECRET_KEY` | required to reconcile and submit |
| `APCA_API_BASE_URL` | `https://paper-api.alpaca.markets` in code; the CronJob sets `https://api.alpaca.markets` |
| `DAYTRADE_DATA_URL` | `https://data.alpaca.markets`; latest trade checked before a buy |
| `DAYTRADE_DATA_FEED` | `iex` |
| `DAYTRADE_EQUITY_OFFSET_USD` | `-99000` in code; the CronJob sets `0` |
| `CURSOR_API_KEY` | unused on the sleeve path |
| `DAYTRADE_DISCORD_WEBHOOK_URL` | unset; startup and decision pings are skipped |

A second CronJob, `daytrader-eod`, runs at 16:10 ET. It posts the account (status, equity, day change versus the prior close, cash, and positions) and does not trade. The startup ping is skipped on that run.

Discord is optional. The process posts a startup message on trading invocations, including ticks that exit before trading. Hold, reject, dry-run, and submit each post as well. HTTP errors do not fail the tick.

## Build

From the repository root:

```sh
nerdctl build -f apps/daytrader/Dockerfile -t daytrader:latest .
```
