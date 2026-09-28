# @daytrade/orchestrator

RTH loop replacing `scripts/hourly_scheduler.py`: prep → fanout → settle.

```bash
npx tsx src/cli.ts --loop --phase prep-then-settle --catch-up
node dist/cli.js --hour 2026-09-25T14 --phase prep --from-fixtures
```

> Future Docker: primary control-plane process. No Dockerfile in v1.
