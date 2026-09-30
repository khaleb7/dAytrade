# Hourly proposal → shared book orders

**Single agent:** `A1` (`grok-4.7`, medium-aggressive) returns one hourly proposal.
That proposal’s valid orders become the settle set (`min_votes=1`). Empty `orders` = **hold** (valid). There is **no** ≥2 multi-agent majority anymore.

Book validation still applies (shared caps, whole-batch reject).

## Shared book caps (match A1)

| Cap | Value |
|-----|-------|
| Cash floor | **8%** |
| Max single name | **45%** |
| Max positions | **7** |

## Flow

1. Prep packs `A1.md` only.
2. Fan-out one local SDK agent → `A1.json`.
3. Build settle file `consensus.json` from A1 (legacy filename; content is the proposal order list).
4. `validate_book` → Alpaca paper submit (or hold / dry-run).

Authoritative roster: `state/roster.json`.
