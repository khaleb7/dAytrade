---
cursor:
  subagentId: "bc-a59dc171-4d66-5b1a-a0c8-c2eb15644d45"
---

# Discord webhook — done

## Env var Josh must set

`DAYTRADE_DISCORD_WEBHOOK_URL`

In `%USERPROFILE%\.daytrade\alpaca.env` (outside the store). Placeholder only in `scripts/windows/alpaca.env.example` and `services/windows/daytrade.env.example`. **Secret was not written into the store.**

Exact PowerShell append line (with real URL) is in the agent reply to the coordinator — not here.

## Events that fire

- Tick start / tick end (compact summary)
- Tick skipped (non-RTH)
- Issue: news/ingest, fan-out agent failures, settle skipped, loop exceptions
- Consensus outcome (orders or `no_consensus`)
- Submit / dry-run outcome
- Day-end analysis start + done (after 15:30)

## Soft-fail

Missing URL → no-op. Bad URL / HTTP errors → warn, never throw into trading path.

## Smoke

Cloud agent POSTed a test embed via Python + Node (both `ok: true`). Soft-fail without env also verified.

## Docs

- `internal/discord-webhook-alerts.md`
- `docs/windows-scheduler.md` (Discord section)
- `docs/control-plane.md` (optional env)

## Restart after sync

Josh needs to append the env var, then restart the hourly loop so it reloads `alpaca.env`.
