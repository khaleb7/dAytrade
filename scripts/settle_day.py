"""Validate batches, fill at open, EOD mark at close, journals + lesson ledger."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import (
    BATCHES,
    LESSONS,
    ROSTER,
    SIM_META,
    agent_dir,
    batch_path,
    journal_dir,
    market_path,
    portfolio_path,
)
from validate_batch import load_json, load_roster, validate_batch


def opens_closes(market: Dict[str, Any]):
    bars = market.get("bars", {})
    opens = {s: float(b["open"]) for s, b in bars.items()}
    closes = {s: float(b["close"]) for s, b in bars.items()}
    return opens, closes


def mark_portfolio(portfolio: Dict[str, Any], closes: Dict[str, float]) -> Dict[str, Any]:
    positions = []
    unreal = 0.0
    equity_pos = 0.0
    for pos in portfolio.get("positions", []):
        sym = pos["symbol"]
        qty = float(pos["qty"])
        avg = float(pos["avg_cost"])
        mark = float(closes.get(sym, pos.get("mark_price", avg)))
        mv = qty * mark
        u = (mark - avg) * qty
        unreal += u
        equity_pos += mv
        positions.append(
            {
                "symbol": sym,
                "qty": qty,
                "avg_cost": avg,
                "mark_price": mark,
                "market_value": mv,
                "unrealized_pnl": u,
            }
        )
    cash = float(portfolio["cash_usd"])
    out = dict(portfolio)
    out["positions"] = positions
    out["equity_usd"] = cash + equity_pos
    out["unrealized_pnl_usd"] = unreal
    return out


def write_journal(agent_id: str, day: str, payload: Dict[str, Any]) -> Path:
    jdir = journal_dir(agent_id)
    jdir.mkdir(parents=True, exist_ok=True)
    path = jdir / f"{day}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def append_lesson(entry: Dict[str, Any], ledger: Path = LESSONS) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    # Drop None fields for cleanliness
    clean = {k: v for k, v in entry.items() if v is not None}
    with ledger.open("a") as f:
        f.write(json.dumps(clean) + "\n")


def settle_agent(
    agent_id: str,
    day: str,
    batch: Optional[Dict[str, Any]],
    market: Dict[str, Any],
    roster: Dict[str, Any],
) -> Dict[str, Any]:
    opens, closes = opens_closes(market)
    port_path = portfolio_path(agent_id)
    portfolio = load_json(port_path)
    equity_start = float(portfolio.get("equity_usd", portfolio.get("cash_usd", 0)))

    rejected = False
    errors: List[str] = []
    fills: List[Dict[str, Any]] = []
    thesis = ""

    if batch is None:
        rejected = True
        errors = ["missing batch — hold"]
        thesis = ""
    else:
        thesis = batch.get("thesis", "")
        result = validate_batch(batch, portfolio, opens, roster, expected_as_of=day)
        if not result["ok"]:
            rejected = True
            errors = result["errors"]
        else:
            post = result["post_trade"]
            # Apply open fills
            portfolio["cash_usd"] = post["cash_usd"]
            portfolio["positions"] = post["positions"]
            portfolio["realized_pnl_usd"] = post["realized_pnl_usd"]
            for order in batch.get("orders", []):
                sym = order["symbol"]
                px = opens[sym]
                if order["side"] == "buy":
                    qty = float(order["notional_usd"]) / px
                    fills.append(
                        {"side": "buy", "symbol": sym, "qty": qty, "price": px, "notional_usd": float(order["notional_usd"])}
                    )
                else:
                    fills.append(
                        {
                            "side": "sell",
                            "symbol": sym,
                            "qty": float(order["qty"]),
                            "price": px,
                            "notional_usd": float(order["qty"]) * px,
                        }
                    )

    # EOD mark
    portfolio = mark_portfolio(portfolio, closes)
    portfolio["agent_id"] = agent_id
    portfolio["as_of"] = day
    day_pnl = float(portfolio["equity_usd"]) - equity_start
    portfolio["day_pnl_usd"] = day_pnl

    port_path.write_text(json.dumps(portfolio, indent=2) + "\n")

    lesson_text = (
        f"{'Batch rejected; held.' if rejected else 'Batch accepted.'} "
        f"Day PnL {day_pnl:+.2f} on equity {portfolio['equity_usd']:.2f}. "
        f"Cash {portfolio['cash_usd']:.2f}; positions {len(portfolio['positions'])}."
    )
    journal = {
        "agent_id": agent_id,
        "date": day,
        "thesis": thesis,
        "batch": batch,
        "accepted": not rejected,
        "reject_errors": errors,
        "fills": fills,
        "eod": {
            "equity_usd": portfolio["equity_usd"],
            "cash_usd": portfolio["cash_usd"],
            "day_pnl_usd": day_pnl,
            "unrealized_pnl_usd": portfolio.get("unrealized_pnl_usd", 0.0),
            "realized_pnl_usd": portfolio.get("realized_pnl_usd", 0.0),
            "positions": portfolio["positions"],
            "lesson": lesson_text,
        },
    }
    jpath = write_journal(agent_id, day, journal)

    # Anonymized lesson — no agent_id
    append_lesson(
        {
            "date": day,
            "accepted": not rejected,
            "day_pnl_usd": round(day_pnl, 4),
            "equity_usd": round(float(portfolio["equity_usd"]), 4),
            "n_positions": len(portfolio["positions"]),
            "lesson": lesson_text,
            "thesis_excerpt": (thesis or "")[:160],
            "recorded_at": datetime.utcnow().isoformat() + "Z",
        }
    )

    return {
        "agent_id": agent_id,
        "accepted": not rejected,
        "errors": errors,
        "equity_usd": portfolio["equity_usd"],
        "day_pnl_usd": day_pnl,
        "journal": str(jpath),
    }


def load_batches_for_day(day: str, batches_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    root = batches_dir or (BATCHES / day)
    out: Dict[str, Dict[str, Any]] = {}
    if not root.exists():
        return out
    for path in sorted(root.glob("A*.json")):
        data = load_json(path)
        aid = data.get("agent_id") or path.stem
        out[aid] = data
    return out


def settle_day(
    day: str,
    market_file: Optional[Path] = None,
    batches_dir: Optional[Path] = None,
    agents: Optional[List[str]] = None,
) -> Dict[str, Any]:
    roster = load_roster()
    market = load_json(market_file or market_path(day))
    agent_ids = agents or list(roster["agents"].keys())
    batches = load_batches_for_day(day, batches_dir if batches_dir else None)
    # If batches_dir points at day folder already
    if batches_dir and not batches:
        batches = load_batches_for_day(day, batches_dir)

    results = []
    for aid in agent_ids:
        results.append(settle_agent(aid, day, batches.get(aid), market, roster))

    summary = {
        "date": day,
        "agents": results,
        "settled_at": datetime.utcnow().isoformat() + "Z",
    }
    out = BATCHES / day / "_settlement.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Settle one trading day for all agents")
    p.add_argument("--date", required=True)
    p.add_argument("--market", type=Path)
    p.add_argument("--batches-dir", type=Path, help="Directory with A1.json…A5.json")
    p.add_argument("--agents", nargs="*")
    args = p.parse_args(argv)

    try:
        summary = settle_day(args.date, args.market, args.batches_dir, args.agents)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
