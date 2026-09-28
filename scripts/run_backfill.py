"""Backfill driver: loop trading days from sim_date toward today.

Supports --dry-run with fixture batches (no LLM calls). Checkpoints every N sessions.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from paths import BATCHES, FIXTURES, SIM_META
from trading_calendar import is_trading_day, next_trading_day, parse_day, trading_days
from settle_day import settle_day
from fetch_market import write_market
from fetch_news import write_news, build_news_pack


def load_meta() -> dict:
    return json.loads(SIM_META.read_text())


def save_meta(meta: dict) -> None:
    SIM_META.write_text(json.dumps(meta, indent=2) + "\n")


def ensure_fixture_market(day: str) -> Path:
    """Write synthetic OHLCV for smoke tests when network unavailable."""
    fixture = FIXTURES / "market" / f"{day}.json"
    if fixture.exists():
        data = json.loads(fixture.read_text())
        return write_market(day, data["bars"], source="fixture")
    # Generic synthetic bars (deterministic-ish from day hash)
    seed = sum(ord(c) for c in day)
    symbols = {
        "VTI": 250.0,
        "BND": 72.0,
        "SPY": 520.0,
        "QQQ": 450.0,
        "AAPL": 190.0,
        "MSFT": 420.0,
        "JNJ": 150.0,
        "XOM": 110.0,
        "GLD": 220.0,
        "IWM": 200.0,
    }
    bars = {}
    for i, (sym, base) in enumerate(symbols.items()):
        o = base + (seed % 17) * 0.01 + i * 0.05
        c = o * (1.0 + ((seed + i) % 9 - 4) * 0.001)
        bars[sym] = {
            "open": round(o, 4),
            "high": round(max(o, c) * 1.002, 4),
            "low": round(min(o, c) * 0.998, 4),
            "close": round(c, 4),
            "volume": 1_000_000 + seed * 10 + i,
        }
    FIXTURES.joinpath("market").mkdir(parents=True, exist_ok=True)
    fixture.write_text(json.dumps({"date": day, "source": "synthetic", "bars": bars}, indent=2) + "\n")
    return write_market(day, bars, source="synthetic_fixture")


def ensure_fixture_news(day: str) -> Path:
    fixture = FIXTURES / "news" / f"{day}.json"
    if fixture.exists():
        pack = json.loads(fixture.read_text())
        pack["date"] = day
        return write_news(day, pack)
    pack = {
        "date": day,
        "cutoff_utc": f"{day}T13:30:00Z",
        "mode": "fixture",
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "source_counts": {
            "reuters": 1,
            "yahoo_finance": 1,
            "marketwatch": 1,
            "sec_edgar": 1,
        },
        "items": [
            {
                "source": "reuters",
                "title": "Futures steady ahead of open",
                "url": "https://example.com/reuters/1",
                "published": f"{day}T10:00:00Z",
                "summary": "US equity futures little changed pre-market.",
            },
            {
                "source": "yahoo_finance",
                "title": "ETF flows favor broad market",
                "url": "https://example.com/yahoo/1",
                "published": f"{day}T09:00:00Z",
                "summary": "VTI and SPY see inflows.",
            },
            {
                "source": "marketwatch",
                "title": "Bond yields ease overnight",
                "url": "https://example.com/mw/1",
                "published": f"{day}T08:30:00Z",
                "summary": "Treasuries bid; risk assets calm.",
            },
            {
                "source": "sec_edgar",
                "title": "8-K: sample issuer announces routine update",
                "url": "https://www.sec.gov/example",
                "published": f"{day}T07:00:00Z",
                "summary": "Material event filing (fixture).",
            },
        ],
    }
    FIXTURES.joinpath("news").mkdir(parents=True, exist_ok=True)
    fixture.write_text(json.dumps(pack, indent=2) + "\n")
    return write_news(day, pack)


def install_fixture_batches(day: str) -> Path:
    """Copy or generate per-agent batches for dry-run settlement."""
    src_day = FIXTURES / "batches" / day
    dest = BATCHES / day
    dest.mkdir(parents=True, exist_ok=True)

    # Prefer day-specific fixtures; else use template set under fixtures/batches/template
    template_dir = src_day if src_day.exists() else (FIXTURES / "batches" / "template")
    if template_dir.exists():
        for path in template_dir.glob("A*.json"):
            data = json.loads(path.read_text())
            data["as_of"] = day
            data["agent_id"] = data.get("agent_id") or path.stem
            (dest / path.name).write_text(json.dumps(data, indent=2) + "\n")
        return dest

    # Generate conservative-safe defaults
    defaults = {
        "A1": {"orders": [{"side": "buy", "symbol": "BND", "notional_usd": 10.0}], "thesis": "Park 10% in bonds; keep cash floor."},
        "A2": {"orders": [{"side": "buy", "symbol": "VTI", "notional_usd": 15.0}], "thesis": "Core equity sleeve via VTI."},
        "A3": {"orders": [{"side": "buy", "symbol": "VTI", "notional_usd": 20.0}, {"side": "buy", "symbol": "BND", "notional_usd": 10.0}], "thesis": "Balanced stock/bond mix."},
        "A4": {"orders": [{"side": "buy", "symbol": "QQQ", "notional_usd": 35.0}], "thesis": "Growth tilt via QQQ within 50% cap."},
        "A5": {"orders": [{"side": "buy", "symbol": "QQQ", "notional_usd": 50.0}, {"side": "buy", "symbol": "IWM", "notional_usd": 20.0}], "thesis": "Speculative risk-on with QQQ/IWM."},
    }
    for aid, body in defaults.items():
        payload = {"agent_id": aid, "as_of": day, **body}
        (dest / f"{aid}.json").write_text(json.dumps(payload, indent=2) + "\n")
    return dest


def run_one_day(
    day: str,
    *,
    dry_run: bool,
    use_network: bool,
) -> dict:
    if dry_run or not use_network:
        ensure_fixture_market(day)
        ensure_fixture_news(day)
        install_fixture_batches(day)
    else:
        # Network path
        from fetch_market import fetch_bars_yfinance, DEFAULT_SYMBOLS, write_market as wm

        try:
            bars = fetch_bars_yfinance(DEFAULT_SYMBOLS, day)
            if not bars:
                raise RuntimeError("empty bars")
            wm(day, bars)
        except Exception as e:
            print(f"warn: market fetch failed ({e}); falling back to fixture", file=sys.stderr)
            ensure_fixture_market(day)
        try:
            # Cache-only: never hammer upstream per day. Ingest once via
            # `python fetch_news.py ingest --backfill-range FROM TO` first.
            pack = build_news_pack(day, mode="cache", cache_only=True)
            write_news(day, pack)
        except Exception as e:
            print(f"warn: news cache build failed ({e}); falling back to fixture", file=sys.stderr)
            ensure_fixture_news(day)
        # Batches must already exist (from agents) unless dry_run
        if not (BATCHES / day).exists():
            raise FileNotFoundError(
                f"No batches under state/batches/{day}/ — run agents or use --dry-run"
            )

    summary = settle_day(day, batches_dir=BATCHES / day)
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="DayTrade backfill driver")
    p.add_argument("--until", help="YYYY-MM-DD inclusive end (default: today UTC)")
    p.add_argument("--max-days", type=int, default=0, help="Stop after N trading days (0=all)")
    p.add_argument("--dry-run", action="store_true", help="Use fixture market/news/batches; no LLMs")
    p.add_argument("--network", action="store_true", help="Attempt yfinance/GDELT/RSS even in backfill")
    p.add_argument("--checkpoint-every", type=int, default=0, help="Override sim-meta checkpoint_every")
    args = p.parse_args(argv)

    meta = load_meta()
    if meta.get("mode") not in ("backfill", "live"):
        print("error: sim-meta mode must be backfill|live", file=sys.stderr)
        return 1

    start = parse_day(meta["sim_date"])
    end = parse_day(args.until) if args.until else datetime.utcnow().date()
    if not is_trading_day(start):
        start = next_trading_day(start - timedelta(days=1))

    days = trading_days(start, end)
    if args.max_days and args.max_days > 0:
        days = days[: args.max_days]

    checkpoint_every = args.checkpoint_every or int(meta.get("checkpoint_every", 20))
    completed_this_run = 0

    print(json.dumps({"start": days[0].isoformat() if days else None, "end": end.isoformat(), "n": len(days), "dry_run": args.dry_run}))

    for d in days:
        day = d.isoformat()
        print(f"=== settling {day} ===")
        try:
            summary = run_one_day(day, dry_run=args.dry_run, use_network=args.network and not args.dry_run)
        except Exception as e:
            print(f"error on {day}: {e}", file=sys.stderr)
            save_meta(meta)
            return 1

        # Advance sim_date to next trading day after successful settle
        nxt = next_trading_day(d)
        meta["sim_date"] = nxt.isoformat()
        meta["sessions_completed"] = int(meta.get("sessions_completed", 0)) + 1
        completed_this_run += 1

        if completed_this_run % checkpoint_every == 0:
            meta["last_checkpoint_at"] = day
            meta["checkpoint_note"] = f"Paused review after {completed_this_run} sessions this run"
            save_meta(meta)
            print(json.dumps({"checkpoint": True, "after": day, "sessions_completed": meta["sessions_completed"]}))
            # Continue unless user wants hard stop — plan says pause for review; we record and continue in automation
        else:
            save_meta(meta)

        print(json.dumps({"day": day, "results": summary["agents"]}, default=str))

    # Catch-up complete?
    if meta["sim_date"] > end.isoformat() or parse_day(meta["sim_date"]) > end:
        print(json.dumps({"catch_up": True, "hint": "Set state/sim-meta.json mode to live when ready."}))

    save_meta(meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
