# SouperMarket

Entertainment only. It does not place orders and Daytrader does not read it.

Daily webpage called Souper Intelligence. After 17:00 America/New_York it files one edition for that Eastern date and serves it, plus every earlier edition.

The image installs `cursor-sdk` in a build stage, then runs on `gcr.io/distroless/python3-debian12` with `PYTHONPATH=/opt/pydeps:/app`. Distroless has no shell, and the SDK bridge launcher is `#!/usr/bin/env sh`, so the image also copies a static `sh` and `env`. The columnists need a writable cwd; the Deployment mounts an emptyDir at `/work`.

## Edition

The publisher polls every 60 seconds.

- If that Eastern date is already stored, it leaves the row alone.
- If the Eastern hour is before `SOUPER_PUBLISH_HOUR_ET` (default 17), it waits.
- If Newstracker has no articles in the 7-day lookback, it waits and does not call the model.
- Otherwise it files the edition and will not overwrite it.

The front page is wire items whose `published` time falls on that Eastern day and before the publish hour. The week section is a count of items and repeated names over the 7-day lookback, not model prose. The three columns are written by three sequential local `Agent.prompt` calls with `tools=[]`, so they return text and do not edit files. The model defaults to `composer-2.5`. An empty or failed column means the edition is not stored and the next poll tries again.

Voices: The Boomer, The Gen Xer, The Millennial. Headlines stay the Newstracker items. The columns quote those headlines.

## Pages

| Path | Behavior |
| --- | --- |
| `GET /health` | `ok` and the number of filed issues |
| `GET /` and `GET /issues` | the latest edition, or a waiting page |
| `GET /issues/YYYY-MM-DD` | that edition, with archive links and Earlier / Later |

SQLite lives at `SOUPER_DB` (default `/data/souper.db`). Newstracker remains the only writer of the news store.

## Environment

| Name | Default |
| --- | --- |
| `SOUPER_DB` | `/data/souper.db` |
| `SOUPER_BIND` | `0.0.0.0` |
| `SOUPER_PORT` | `8080` |
| `NEWSTRACKER_URL` | `http://newstracker.daytrade.svc.cluster.local:8080` |
| `SOUPER_PUBLISH_HOUR_ET` | `17` |
| `SOUPER_POLL_SECONDS` | `60` |
| `SOUPER_WORK` | `/work` |
| `SOUPER_MODEL` | `composer-2.5` |
| `CURSOR_API_KEY` | required to file an edition |
| `DAYTRADE_DISCORD_WEBHOOK_URL` | unset; the startup ping is skipped |

## Build

From the repository root:

```sh
nerdctl build -f apps/soupermarket/Dockerfile -t soupermarket:latest .
```
