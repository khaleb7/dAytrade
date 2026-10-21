# SouperMarket

Read-only day recap. It does not place orders, and Daytrader does not read it.

`GET /` shows the latest session's fills, the account equity and day change, what is held, and a chart of the account against SPY, QQQ, and DIA. Each series is rebased to $1,000 on the first day of the account history. Index closes are IEX. The page is built on request and cached for 45 seconds.

`GET /health` returns `{"ok": true}`.

## Environment

| Name | Default |
| --- | --- |
| `SOUPER_BIND` | `0.0.0.0` |
| `SOUPER_PORT` | `8080` |
| `APCA_API_KEY_ID` | required to read the account |
| `APCA_API_SECRET_KEY` | required to read the account |
| `APCA_API_BASE_URL` | `https://api.alpaca.markets` |
| `SOUPER_DATA_URL` | `https://data.alpaca.markets` |
| `DAYTRADE_DISCORD_WEBHOOK_URL` | unset; the startup ping is skipped |

## Build

From the repository root:

```sh
nerdctl build -f apps/soupermarket/Dockerfile -t soupermarket:latest .
```
