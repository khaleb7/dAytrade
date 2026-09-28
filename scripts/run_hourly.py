"""Orchestrate one Alpaca paper hourly consensus tick.

Default is dry-run (no order submit). Use --submit to place paper orders after
consensus + book validation succeed.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from hour_bucket import is_rth_consensus_hour, parse_hour_bucket
from paths import BOOK_PORTFOLIO, FIXTURES, hourly_consensus_path, hourly_dir, hourly_news_path

AGENT_IDS = ["A1", "A2", "A3", "A4", "A5"]


def _iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def copy_fixture_proposals(day: str, hour: int) -> List[str]:
    src = FIXTURES / "hourly" / "proposals"
    dest = hourly_dir(day, hour)
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for aid in AGENT_IDS:
        s = src / f"{aid}.json"
        if s.exists():
            shutil.copy2(s, dest / f"{aid}.json")
            copied.append(aid)
    return copied


def run_hour(args: argparse.Namespace) -> Dict[str, Any]:
    phase = getattr(args, "phase", "full") or "full"
    if phase == "settle":
        args.skip_ingest = True
        args.skip_news = True
        args.skip_packs = True

    day_d, hour, as_of = parse_hour_bucket(args.hour, utc=args.utc)
    day = day_d.isoformat()
    out_dir = hourly_dir(day, hour)
    out_dir.mkdir(parents=True, exist_ok=True)

    report: Dict[str, Any] = {
        "as_of": as_of,
        "day": day,
        "hour_et": f"{hour:02d}",
        "started_at": _iso_z(),
        "dry_run": not args.submit,
        "steps": {},
    }

    if not args.allow_non_rth and not is_rth_consensus_hour(day_d, hour):
        report["error"] = f"{as_of} outside RTH consensus hours (10–15 ET trading day)"
        _write_json(out_dir / "settle.json", report)
        return report

    # --- 1) News ingest ---
    if not args.skip_ingest:
        from fetch_news import ingest_live_feeds

        try:
            report["steps"]["ingest"] = ingest_live_feeds()
        except Exception as e:  # noqa: BLE001
            report["steps"]["ingest"] = {"error": str(e)}
            if not args.continue_on_ingest_error:
                report["error"] = "ingest failed"
                _write_json(out_dir / "settle.json", report)
                return report
    else:
        report["steps"]["ingest"] = {"skipped": True}

    # --- 2) Build hour news pack ---
    if not args.skip_news:
        from fetch_news import build_hour_pack

        fixture_news = (FIXTURES / "hourly" / "news.json") if args.from_fixtures else None
        try:
            path, pack = build_hour_pack(
                args.hour,
                cache_only=not args.from_fixtures,
                utc=args.utc,
                fixture=fixture_news if args.from_fixtures else None,
            )
            # If not from fixtures but cache empty and fixtures exist, soft fallback
            report["steps"]["news"] = {
                "wrote": str(path),
                "items": len(pack.get("items", [])),
                "mode": pack.get("mode"),
            }
        except FileNotFoundError as e:
            if args.from_fixtures or (FIXTURES / "hourly" / "news.json").exists():
                path, pack = build_hour_pack(
                    args.hour,
                    cache_only=False,
                    utc=args.utc,
                    fixture=FIXTURES / "hourly" / "news.json",
                )
                report["steps"]["news"] = {
                    "wrote": str(path),
                    "items": len(pack.get("items", [])),
                    "mode": "fixture_fallback",
                    "warning": str(e),
                }
            else:
                report["steps"]["news"] = {"error": str(e)}
                report["error"] = "news build failed"
                _write_json(out_dir / "settle.json", report)
                return report
    else:
        report["steps"]["news"] = {"skipped": True, "path": str(hourly_news_path(day, hour))}

    # --- 3) Reconcile Alpaca book (optional) ---
    from alpaca_client import AlpacaClient, ensure_config

    ensure_config()
    if args.reconcile or (AlpacaClient.credentials_present() and not args.skip_reconcile):
        if AlpacaClient.credentials_present():
            try:
                client = AlpacaClient()
                mirror = client.reconcile(BOOK_PORTFOLIO)
                report["steps"]["reconcile"] = {
                    "equity_usd": mirror.get("equity_usd"),
                    "cash_usd": mirror.get("cash_usd"),
                    "positions": len(mirror.get("positions") or []),
                    "wrote": str(BOOK_PORTFOLIO),
                }
            except Exception as e:  # noqa: BLE001
                report["steps"]["reconcile"] = {"error": str(e)}
        else:
            report["steps"]["reconcile"] = {"skipped": True, "reason": "no_credentials"}
    else:
        report["steps"]["reconcile"] = {"skipped": True}

    # Seed book from fixtures if still empty seed and from-fixtures
    if args.from_fixtures and not BOOK_PORTFOLIO.exists():
        shutil.copy2(FIXTURES / "hourly" / "book" / "portfolio.json", BOOK_PORTFOLIO)

    # --- 4) Build agent packs ---
    if not args.skip_packs:
        from build_hourly_packs import build_hourly_packs

        book_path = BOOK_PORTFOLIO
        if args.from_fixtures and (FIXTURES / "hourly" / "book" / "portfolio.json").exists():
            # Prefer live reconciled book if present with equity; else fixture
            pass
        paths = build_hourly_packs(day, hour, book_path=book_path)
        report["steps"]["packs"] = {"wrote": [str(p) for p in paths]}
    else:
        report["steps"]["packs"] = {"skipped": True}

    # --- 5) Fan-out placeholder / fixtures ---
    phase = getattr(args, "phase", "full") or "full"
    if args.from_fixtures:
        copied = copy_fixture_proposals(day, hour)
        report["steps"]["fanout"] = {
            "mode": "fixtures",
            "copied": copied,
            "note": "Coordinator fan-out skipped; fixture proposals installed.",
        }
        missing: List[str] = []
    else:
        missing = [a for a in AGENT_IDS if not (out_dir / f"{a}.json").exists()]
        report["steps"]["fanout"] = {
            "mode": "placeholder",
            "missing_proposals": missing,
            "note": (
                "Launch five cloud agents with packs A1.md…A5.md; write A1.json…A5.json here. "
                "Re-run with --phase settle (or --skip-ingest --skip-packs --skip-news) after proposals land."
            ),
        }

    if phase == "prep":
        ready = {
            "as_of": as_of,
            "day": day,
            "hour_et": f"{hour:02d}",
            "packs": [str(out_dir / f"{a}.md") for a in AGENT_IDS],
            "ready_at": _iso_z(),
            "missing_proposals": missing,
            "next": "Fan out A1–A5, then: python run_hourly.py --hour … --phase settle",
        }
        _write_json(out_dir / "ready.json", ready)
        report["steps"]["ready"] = ready
        report["phase"] = "prep"
        report["finished_at"] = _iso_z()
        _write_json(out_dir / "settle.json", report)
        return report

    if (not args.from_fixtures) and missing and not args.allow_missing_proposals:
        report["error"] = "missing proposals (use --phase prep, --from-fixtures, or wait for fan-out)"
        _write_json(out_dir / "settle.json", report)
        return report

    # --- 6) Consensus ---
    from consensus import build_consensus, load_proposals, write_consensus

    proposals, missing_agents = load_proposals(day, hour)
    book = json.loads(BOOK_PORTFOLIO.read_text()) if BOOK_PORTFOLIO.exists() else {
        "cash_usd": 1000.0,
        "positions": [],
        "equity_usd": 1000.0,
    }
    held = {p["symbol"]: float(p["qty"]) for p in book.get("positions") or []}
    consensus = build_consensus(proposals, as_of=as_of, held_qty=held)
    if missing_agents:
        consensus["missing_agents"] = missing_agents
    cpath = write_consensus(day, hour, consensus)
    report["steps"]["consensus"] = {
        "wrote": str(cpath),
        "orders": consensus.get("orders"),
        "no_consensus": consensus.get("no_consensus"),
        "rejected_legs": consensus.get("rejected_legs"),
    }

    # --- 7) Validate book ---
    from validate_book import validate_book

    prices = None
    prices_path = Path(args.prices) if args.prices else (FIXTURES / "hourly" / "prices.json")
    if prices_path.exists():
        prices = json.loads(prices_path.read_text())
    validation = validate_book(consensus, book, prices)
    report["steps"]["validate"] = validation

    # --- 8) Submit or dry-run ---
    submit_results: List[Dict[str, Any]] = []
    if not validation.get("ok"):
        report["steps"]["submit"] = {"skipped": True, "reason": "validation_failed"}
    elif consensus.get("no_consensus") or not consensus.get("orders"):
        report["steps"]["submit"] = {"skipped": True, "reason": "no_consensus"}
    elif not args.submit:
        from alpaca_client import submit_consensus_orders

        submit_results = submit_consensus_orders(None, consensus["orders"], dry_run=True)
        report["steps"]["submit"] = {
            "dry_run": True,
            "orders": submit_results,
            "note": "Pass --submit to place Alpaca paper market orders (defaults off).",
        }
    else:
        if not AlpacaClient.credentials_present():
            report["steps"]["submit"] = {"error": "credentials missing; cannot --submit"}
            report["error"] = "submit requested without credentials"
        else:
            from alpaca_client import submit_consensus_orders

            client = AlpacaClient()
            submit_results = submit_consensus_orders(client, consensus["orders"], dry_run=False)
            report["steps"]["submit"] = {"dry_run": False, "orders": submit_results}
            # Reconcile after submit
            try:
                mirror = client.reconcile(BOOK_PORTFOLIO)
                report["steps"]["post_reconcile"] = {
                    "equity_usd": mirror.get("equity_usd"),
                    "cash_usd": mirror.get("cash_usd"),
                }
            except Exception as e:  # noqa: BLE001
                report["steps"]["post_reconcile"] = {"error": str(e)}

    report["finished_at"] = _iso_z()
    _write_json(out_dir / "settle.json", report)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Run one hourly Alpaca consensus tick")
    p.add_argument("--hour", required=True, help="Hour bucket YYYY-MM-DDTHH (ET default)")
    p.add_argument("--utc", action="store_true", help="Interpret hour as UTC")
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Do not submit orders (default). Kept for clarity; omit --submit.",
    )
    p.add_argument(
        "--submit",
        action="store_true",
        help="Submit consensus orders to Alpaca paper (OFF by default). Implies not dry-run.",
    )
    p.add_argument(
        "--phase",
        choices=["full", "prep", "settle"],
        default="full",
        help="full=ingest→consensus; prep=stop after packs/ready.json; settle=consensus from existing proposals",
    )
    p.add_argument("--skip-ingest", action="store_true")
    p.add_argument("--skip-news", action="store_true")
    p.add_argument("--skip-packs", action="store_true")
    p.add_argument("--skip-reconcile", action="store_true")
    p.add_argument("--reconcile", action="store_true", help="Force reconcile when credentials present")
    p.add_argument("--from-fixtures", action="store_true", help="Use fixture news + proposals (smoke)")
    p.add_argument("--allow-missing-proposals", action="store_true")
    p.add_argument("--allow-non-rth", action="store_true")
    p.add_argument("--continue-on-ingest-error", action="store_true")
    p.add_argument("--prices", type=Path, help="Mark prices JSON for validation")
    args = p.parse_args(argv)

    # --dry-run is default; --submit turns it off
    if not args.submit:
        args.submit = False

    report = run_hour(args)
    print(json.dumps(report, indent=2))
    if report.get("error"):
        return 2
    val = report.get("steps", {}).get("validate", {})
    if val and not val.get("ok", True):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
