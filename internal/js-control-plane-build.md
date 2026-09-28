---
cursor:
  subagentId: "bc-a59dc171-4d66-5b1a-a0c8-c2eb15644d45"
---

# JS/TS control plane — build notes

Hybrid multi-package control plane landed under `services/`. Smokes ran from a local-disk npm install (`/tmp/daytrade-services-build`) because Project-store FUSE made in-place `npm install` / `rm -rf node_modules` hang (EAGAIN / multi-minute tar extracts).

## Verified

- `npm run build` (all workspaces) — OK after fanout SDK cast + orchestrator import fix
- Book sizing: 100000 + offset −99000 → sizing equity **1000**
- Consensus fixtures: majority VTI buy @ 50 (3/5)
- Orchestrator `prep` / `settle` / `full` with `--from-fixtures`
- `--next-tick` → next RTH bucket

## Layout

See `docs/control-plane.md`. Windows entry: `scripts/windows/Start-HourlyScheduler.ps1` → Node orchestrator (Python fallback).
