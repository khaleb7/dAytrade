"""Live cadence: morning pack build + EOD settlement.

Usage:
  python run_live.py morning [--date YYYY-MM-DD]
  python run_live.py eod [--date YYYY-MM-DD] [--dry-run]

Switching from backfill: set state/sim-meta.json "mode" to "live" after catch-up.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from paths import BATCHES, SIM_META, market_path, news_path
from trading_calendar import is_trading_day, parse_day, rth_open_utc_iso
from fetch_news import build_news_pack, write_news
from fetch_market import DEFAULT_SYMBOLS, fetch_bars_yfinance, write_market
from settle_day import settle_day
from run_backfill import ensure_fixture_market, ensure_fixture_news, install_fixture_batches


def load_meta() -> dict:
    return json.loads(SIM_META.read_text())


def save_meta(meta: dict) -> None:
    SIM_META.write_text(json.dumps(meta, indent=2) + "\n")


def resolve_day(explicit: Optional[str]) -> str:
    meta = load_meta()
    if explicit:
        return explicit
    return meta["sim_date"]


def cmd_morning(day: str, *, dry_run: bool, network: bool) -> int:
    d = parse_day(day)
    if not is_trading_day(d):
        print(f"error: {day} is not a trading day", file=sys.stderr)
        return 1

    meta = load_meta()
    if meta.get("mode") != "live":
        print(
            json.dumps(
                {
                    "warn": "sim-meta mode is not live",
                    "mode": meta.get("mode"),
                    "hint": "After backfill catch-up, set mode to live",
                }
            )
        )

    if dry_run or not network:
        mpath = ensure_fixture_market(day)
        npath = ensure_fixture_news(day)
    else:
        try:
            bars = fetch_bars_yfinance(DEFAULT_SYMBOLS, day)
            if not bars:
                raise RuntimeError("empty bars")
            mpath = write_market(day, bars)
        except Exception as e:
            print(f"warn: market fetch failed ({e}); fixture fallback", file=sys.stderr)
            mpath = ensure_fixture_market(day)
        try:
            pack = build_news_pack(day, mode="live")
            npath = write_news(day, pack)
        except Exception as e:
            print(f"warn: news fetch failed ({e}); fixture fallback", file=sys.stderr)
            npath = ensure_fixture_news(day)

    # Morning does not settle — agents still need to produce batches.
    pack_note = {
        "phase": "morning",
        "date": day,
        "cutoff_utc": rth_open_utc_iso(day),
        "market": str(mpath),
        "news": str(npath),
        "next": "Fan out 5 cloud agents (see docs/orchestration.md); write batches to state/batches/{date}/A*.json; then run eod.",
    }
    print(json.dumps(pack_note, indent=2))
    return 0


def cmd_eod(day: str, *, dry_run: bool) -> int:
    d = parse_day(day)
    if not is_trading_day(d):
        print(f"error: {day} is not a trading day", file=sys.stderr)
        return 1

    if not market_path(day).exists():
        if dry_run:
            ensure_fixture_market(day)
        else:
            print(f"error: missing market file {market_path(day)}", file=sys.stderr)
            return 1

    if dry_run:
        install_fixture_batches(day)

    if not (BATCHES / day).exists():
        print(f"error: no batches for {day}", file=sys.stderr)
        return 1

    summary = settle_day(day, batches_dir=BATCHES / day)
    meta = load_meta()
    from trading_calendar import next_trading_day

    meta["sim_date"] = next_trading_day(d).isoformat()
    meta["sessions_completed"] = int(meta.get("sessions_completed", 0)) + 1
    meta["last_live_eod"] = day
    save_meta(meta)
    print(json.dumps(summary, indent=2))
    return 0


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="Live morning/EOD DayTrade runner")
    p.add_argument("phase", choices=["morning", "eod"])
    p.add_argument("--date")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--network", action="store_true", help="Fetch live market/news")
    args = p.parse_args(argv)

    day = resolve_day(args.date)
    if args.phase == "morning":
        return cmd_morning(day, dry_run=args.dry_run, network=args.network)
    return cmd_eod(day, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
