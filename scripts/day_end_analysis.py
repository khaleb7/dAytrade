"""Build day-end analysis for Alpaca paper RTH consensus.

Writes state/daily/YYYY-MM-DD/analysis.json and appends an anonymized lesson
to state/lessons/ledger.jsonl for next-day / ongoing fan-out packs.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import (
    BOOK_PORTFOLIO,
    HOURLY,
    LESSONS,
    daily_dir,
    day_end_analysis_path,
)
from trading_calendar import is_trading_day, parse_day


def _iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _append_lesson(entry: Dict[str, Any]) -> None:
    LESSONS.parent.mkdir(parents=True, exist_ok=True)
    with LESSONS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def _slot_sort_key(name: str) -> tuple:
    # Prefer HHMM dirs; legacy HH sorts as HH00
    if len(name) == 4 and name.isdigit():
        return (int(name[:2]), int(name[2:]))
    if len(name) <= 2 and name.isdigit():
        return (int(name), 0)
    return (99, 0)


def collect_ticks(day: str) -> List[Dict[str, Any]]:
    root = HOURLY / day
    if not root.exists():
        return []
    ticks: List[Dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: _slot_sort_key(p.name)):
        if not child.is_dir():
            continue
        slot = child.name
        row: Dict[str, Any] = {"slot": slot, "path": str(child)}
        consensus_p = child / "consensus.json"
        settle_p = child / "settle.json"
        fanout_p = child / "fanout.json"
        if consensus_p.exists():
            try:
                c = _load_json(consensus_p)
                row["consensus"] = {
                    "as_of": c.get("as_of"),
                    "no_consensus": c.get("no_consensus"),
                    "orders": c.get("orders") or [],
                    "rejected_legs": c.get("rejected_legs") or [],
                    "min_votes": c.get("min_votes"),
                    "proposals_loaded": c.get("proposals_loaded") or [],
                }
            except Exception as e:  # noqa: BLE001
                row["consensus_error"] = str(e)
        if settle_p.exists():
            try:
                s = _load_json(settle_p)
                submit = (s.get("steps") or {}).get("submit") or {}
                row["settle"] = {
                    "dry_run": s.get("dry_run"),
                    "error": s.get("error"),
                    "submit": submit,
                    "validate_ok": ((s.get("steps") or {}).get("validate") or {}).get("ok"),
                }
            except Exception as e:  # noqa: BLE001
                row["settle_error"] = str(e)
        if fanout_p.exists():
            try:
                f = _load_json(fanout_p)
                row["fanout_mode"] = f.get("mode")
                row["fanout_agents"] = [
                    {"agent_id": a.get("agent_id"), "status": a.get("status"), "model_id": a.get("model_id")}
                    for a in (f.get("agents") or [])
                ]
            except Exception as e:  # noqa: BLE001
                row["fanout_error"] = str(e)
        ticks.append(row)
    return ticks


def build_analysis(day: str) -> Dict[str, Any]:
    ticks = collect_ticks(day)
    orders_all: List[Dict[str, Any]] = []
    consensus_ticks = 0
    no_consensus = 0
    submitted = 0
    dry_runs = 0
    symbols: Dict[str, int] = {}

    for t in ticks:
        c = t.get("consensus") or {}
        orders = c.get("orders") or []
        if c:
            if c.get("no_consensus") or not orders:
                no_consensus += 1
            else:
                consensus_ticks += 1
                for o in orders:
                    orders_all.append({**o, "slot": t.get("slot")})
                    sym = o.get("symbol")
                    if sym:
                        symbols[sym] = symbols.get(sym, 0) + 1
        settle = t.get("settle") or {}
        submit = settle.get("submit") or {}
        if submit.get("dry_run") is True:
            dry_runs += 1
        if submit.get("dry_run") is False or (
            isinstance(submit.get("orders"), list)
            and submit.get("dry_run") is False
        ):
            submitted += 1
        if settle.get("submit") and not submit.get("skipped") and submit.get("dry_run") is False:
            pass  # counted above

    book = {}
    if BOOK_PORTFOLIO.exists():
        try:
            book = _load_json(BOOK_PORTFOLIO)
        except Exception:  # noqa: BLE001
            book = {}

    top_symbols = sorted(symbols.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    lessons: List[str] = []
    if consensus_ticks == 0 and ticks:
        lessons.append("No settle orders filled any tick today — A1 held or book validation rejected.")
    if top_symbols:
        lessons.append(
            "Most agreed symbols: " + ", ".join(f"{s}×{n}" for s, n in top_symbols) + "."
        )
    if submitted:
        lessons.append(f"Paper submits on {submitted} tick(s); dry-run-only ticks: {dry_runs}.")
    if not lessons:
        lessons.append("Quiet or incomplete session — review tick folders under state/hourly.")

    brief_lines = [
        f"Day-end {day} (RTH half-hour cadence).",
        f"Ticks observed: {len(ticks)}; consensus: {consensus_ticks}; no_consensus: {no_consensus}.",
        f"Book equity≈{book.get('equity_usd')} cash≈{book.get('cash_usd')} positions={len(book.get('positions') or [])}.",
        *lessons,
        "Use this brief plus the anonymized ledger; do not invent fills that did not happen.",
    ]
    for o in orders_all[:12]:
        side = o.get("side")
        sym = o.get("symbol")
        slot = o.get("slot")
        if side == "buy":
            brief_lines.append(f"- {slot}: buy {sym} notional={o.get('notional_usd')} votes={o.get('votes')}")
        else:
            brief_lines.append(f"- {slot}: sell {sym} qty={o.get('qty')} votes={o.get('votes')}")

    analysis: Dict[str, Any] = {
        "date": day,
        "generated_at": _iso_z(),
        "cadence": "30m",
        "rth": "09:30-15:30 ET",
        "stats": {
            "ticks": len(ticks),
            "consensus_ticks": consensus_ticks,
            "no_consensus_ticks": no_consensus,
            "orders": len(orders_all),
            "submitted_ticks": submitted,
            "dry_run_ticks": dry_runs,
            "top_symbols": [{"symbol": s, "ticks": n} for s, n in top_symbols],
        },
        "orders": orders_all,
        "ticks": ticks,
        "book_snapshot": {
            "equity_usd": book.get("equity_usd"),
            "cash_usd": book.get("cash_usd"),
            "positions": book.get("positions") or [],
        },
        "lessons": lessons,
        "for_next_session": "\n".join(brief_lines),
    }
    return analysis


def write_analysis(day: str, *, append_lesson: bool = True) -> Dict[str, Any]:
    analysis = build_analysis(day)
    out = day_end_analysis_path(day)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
    # Human-readable sibling for packs / inspection
    md = daily_dir(day) / "analysis.md"
    md.write_text(analysis.get("for_next_session") or "", encoding="utf-8")

    if append_lesson:
        _append_lesson(
            {
                "date": day,
                "kind": "day_end_rth",
                "accepted": True,
                "day_pnl_usd": None,
                "equity_usd": (analysis.get("book_snapshot") or {}).get("equity_usd"),
                "n_positions": len((analysis.get("book_snapshot") or {}).get("positions") or []),
                "lesson": "; ".join(analysis.get("lessons") or [])[:400],
                "thesis_excerpt": (analysis.get("for_next_session") or "")[:240],
                "recorded_at": _iso_z(),
            }
        )
    return analysis


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Build RTH day-end analysis for fan-out packs")
    p.add_argument("--date", required=True, help="Trading day YYYY-MM-DD")
    p.add_argument("--no-lesson", action="store_true", help="Do not append ledger lesson")
    args = p.parse_args(argv)

    day = args.date
    try:
        d = parse_day(day)
    except Exception as e:  # noqa: BLE001
        print(f"error: bad date: {e}", file=sys.stderr)
        return 1
    if not is_trading_day(d):
        print(f"warning: {day} is not an NYSE trading day", file=sys.stderr)

    analysis = write_analysis(day, append_lesson=not args.no_lesson)
    print(json.dumps({"wrote": str(day_end_analysis_path(day)), "stats": analysis.get("stats")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
