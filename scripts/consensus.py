"""Single-agent proposal → book orders (ex-majority consensus).

A1 (grok-4.7) writes the hourly proposal; min_votes=1 so that agent's
valid legs become the settle set. Empty orders = hold (valid).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from paths import hourly_consensus_path, hourly_dir, active_agent_ids

MIN_VOTES = 1


def load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def _median(vals: List[float]) -> float:
    return float(statistics.median(vals))


def load_proposals(
    day: str,
    hour_or_slot: int | str,
    *,
    proposals_dir: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Load proposals for roster agents with model_id. Missing files are skipped (reported)."""
    base = proposals_dir or hourly_dir(day, hour_or_slot)
    loaded: List[Dict[str, Any]] = []
    missing: List[str] = []
    for aid in active_agent_ids():
        path = base / f"{aid}.json"
        if not path.exists():
            missing.append(aid)
            continue
        data = load_json(path)
        if not isinstance(data, dict):
            missing.append(aid)
            continue
        data.setdefault("agent_id", aid)
        loaded.append(data)
    return loaded, missing


def build_consensus(
    proposals: List[Dict[str, Any]],
    *,
    as_of: Optional[str] = None,
    held_qty: Optional[Dict[str, float]] = None,
    min_votes: int = MIN_VOTES,
) -> Dict[str, Any]:
    """Group by (symbol, side); require ≥min_votes (1 for single-agent); median size among voters.

    Empty-order agents do not count toward any leg's votes.
    """
    held_qty = held_qty or {}
    as_of = as_of or next((p.get("as_of") for p in proposals if p.get("as_of")), None)

    # leg_key -> list of (agent_id, size)
    buckets: Dict[Tuple[str, str], List[Tuple[str, float]]] = {}
    rejected_legs: List[Dict[str, Any]] = []
    proposals_loaded = []

    for prop in proposals:
        aid = prop.get("agent_id")
        proposals_loaded.append(aid)
        orders = prop.get("orders") or []
        if not isinstance(orders, list):
            continue
        for o in orders:
            if not isinstance(o, dict):
                continue
            side = o.get("side")
            symbol = o.get("symbol")
            if side not in ("buy", "sell") or not isinstance(symbol, str):
                rejected_legs.append({"reason": "bad_order_shape", "agent": aid, "order": o})
                continue
            symbol = symbol.upper()
            if side == "buy":
                size = o.get("notional_usd")
                if not isinstance(size, (int, float)) or size <= 0:
                    rejected_legs.append({"reason": "bad_buy_notional", "agent": aid, "order": o})
                    continue
                size = float(size)
            else:
                size = o.get("qty")
                if not isinstance(size, (int, float)) or size <= 0:
                    rejected_legs.append({"reason": "bad_sell_qty", "agent": aid, "order": o})
                    continue
                size = float(size)
            buckets.setdefault((symbol, side), []).append((aid, size))

    orders_out: List[Dict[str, Any]] = []
    for (symbol, side), votes in sorted(buckets.items()):
        agents = [a for a, _ in votes]
        sizes = [s for _, s in votes]
        if len(votes) < min_votes:
            rejected_legs.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "votes": len(votes),
                    "agents": agents,
                    "reason": "below_majority",
                }
            )
            continue
        med = _median(sizes)
        if side == "buy":
            med = round(med, 2)
            orders_out.append(
                {
                    "side": "buy",
                    "symbol": symbol,
                    "notional_usd": med,
                    "votes": len(votes),
                    "agents": agents,
                }
            )
        else:
            held = float(held_qty.get(symbol, 0.0))
            qty = round(med, 6)
            if held > 0 and qty > held:
                qty = round(held, 6)
            orders_out.append(
                {
                    "side": "sell",
                    "symbol": symbol,
                    "qty": qty,
                    "votes": len(votes),
                    "agents": agents,
                    "scaled_to_held": held > 0 and med > held + 1e-12,
                }
            )

    return {
        "as_of": as_of,
        "orders": orders_out,
        "rejected_legs": rejected_legs,
        "no_consensus": len(orders_out) == 0,
        "proposals_loaded": [a for a in proposals_loaded if a],
        "min_votes": min_votes,
    }


def write_consensus(day: str, hour_or_slot: int | str, consensus: Dict[str, Any]) -> Path:
    path = hourly_consensus_path(day, hour_or_slot)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(consensus, indent=2) + "\n")
    return path


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Build settle orders from A1 proposal (min_votes=1)")
    p.add_argument("--day", help="YYYY-MM-DD (ET)")
    p.add_argument("--hour", type=int, help="ET hour 0-23")
    p.add_argument("--bucket", help="YYYY-MM-DDTHH (alternative to --day/--hour)")
    p.add_argument("--proposals-dir", type=Path, help="Directory with A1.json")
    p.add_argument("--portfolio", type=Path, help="Book portfolio for sell qty scaling")
    p.add_argument("--out", type=Path, help="Output consensus.json path")
    p.add_argument("--min-votes", type=int, default=MIN_VOTES)
    args = p.parse_args(argv)

    day = args.day
    hour = args.hour
    if args.bucket:
        from hour_bucket import parse_hour_bucket

        d, h, minute, slot, _ = parse_hour_bucket(args.bucket)
        day = d.isoformat()
        hour = slot  # path key HHMM
    if args.proposals_dir and (day is None or hour is None):
        # allow fixtures without day/hour if --out given
        proposals, missing = [], []
        base = args.proposals_dir
        for aid in active_agent_ids():
            path = base / f"{aid}.json"
            if path.exists():
                proposals.append(load_json(path))
            else:
                missing.append(aid)
    else:
        if day is None or hour is None:
            print("error: need --bucket or --day + --hour", file=sys.stderr)
            return 1
        proposals, missing = load_proposals(day, hour, proposals_dir=args.proposals_dir)

    held: Dict[str, float] = {}
    if args.portfolio and args.portfolio.exists():
        port = load_json(args.portfolio)
        for pos in port.get("positions") or []:
            held[pos["symbol"]] = float(pos["qty"])

    as_of = next((p.get("as_of") for p in proposals if p.get("as_of")), None)
    consensus = build_consensus(proposals, as_of=as_of, held_qty=held, min_votes=args.min_votes)
    if missing:
        consensus["missing_agents"] = missing

    out = args.out
    if out is None and day is not None and hour is not None:
        out = write_consensus(day, hour, consensus)
    elif out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(consensus, indent=2) + "\n")
    print(json.dumps(consensus, indent=2))
    if out:
        print(json.dumps({"wrote": str(out)}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
