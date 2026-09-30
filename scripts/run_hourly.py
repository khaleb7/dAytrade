"""Orchestrate one Alpaca paper hourly consensus tick.

Paper Alpaca submit is ON by default (paper-only account). Pass --dry-run to
skip live paper orders after consensus + book validation.
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
from paths import BOOK_PORTFOLIO, FIXTURES, active_agent_ids, hourly_consensus_path, hourly_dir, hourly_news_path

try:
    from discord_notify import notify as discord_notify
except Exception:  # noqa: BLE001
    def discord_notify(*_a: Any, **_k: Any) -> bool:  # type: ignore[misc]
        return False


def _iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _summarize_orders(orders: Any) -> str:
    if not isinstance(orders, list) or not orders:
        return "none"
    parts = []
    for o in orders[:8]:
        if not isinstance(o, dict):
            continue
        votes = o.get("votes")
        agents = o.get("agents")
        vote_bit = ""
        if isinstance(votes, int):
            agent_s = ",".join(str(a) for a in agents) if isinstance(agents, list) else ""
            vote_bit = f" ({votes}v{(':' + agent_s) if agent_s else ''})"
        if o.get("side") == "buy":
            parts.append(f"buy {o.get('symbol')} ${o.get('notional_usd')}{vote_bit}")
        else:
            parts.append(f"sell {o.get('symbol')} qty={o.get('qty')}{vote_bit}")
    return "\n".join(parts) or "none"


def _summarize_rejected(legs: Any) -> str:
    if not isinstance(legs, list) or not legs:
        return ""
    parts = []
    for leg in legs[:8]:
        if not isinstance(leg, dict):
            continue
        if leg.get("reason") == "below_majority":
            agents = ",".join(str(a) for a in (leg.get("agents") or []))
            parts.append(
                f"{leg.get('side')} {leg.get('symbol')} {leg.get('votes', '?')}v"
                f"{f' ({agents})' if agents else ''} — below majority"
            )
        else:
            parts.append(
                f"{leg.get('reason') or 'rejected'}"
                f"{(' ' + str(leg.get('symbol'))) if leg.get('symbol') else ''}"
                f"{(' @' + str(leg.get('agent'))) if leg.get('agent') else ''}"
            )
    return "\n".join(parts)


def _format_consensus_body(consensus: Dict[str, Any]) -> str:
    lines: List[str] = []
    min_votes = consensus.get("min_votes") or 2
    loaded = consensus.get("proposals_loaded") or []
    if isinstance(loaded, list) and loaded:
        lines.append(f"loaded: {','.join(str(a) for a in loaded)} · min_votes≥{min_votes}")
    missing = consensus.get("missing_agents") or []
    if missing:
        lines.append(f"missing: {','.join(str(a) for a in missing)}")
    orders = consensus.get("orders") or []
    if consensus.get("no_consensus") or not orders:
        is_hold = int(consensus.get("min_votes") or 1) <= 1
        lines.append("result: hold (no orders)" if is_hold else "result: no_consensus")
        rejected = _summarize_rejected(consensus.get("rejected_legs"))
        if rejected:
            lines.append("rejected legs:")
            lines.append(rejected)
        elif is_hold:
            lines.append("(single agent chose empty orders — valid hold)")
        else:
            lines.append("(no majority legs — typically all holds)")
    else:
        lines.append("orders:")
        lines.append(_summarize_orders(orders))
    return "\n".join(lines)[:1800]


def _notify_tick_outcome(bucket: str, report: Dict[str, Any]) -> None:
    """Soft Discord summary for Python fallback path (never raises)."""
    try:
        steps = report.get("steps") or {}
        err = report.get("error")
        if err:
            discord_notify(f"Issue · {bucket}", str(err), kind="issue", ok=False)
        consensus = steps.get("consensus") or {}
        if consensus:
            orders = consensus.get("orders") or []
            order_n = len(orders) if isinstance(orders, list) else 0
            rejected = consensus.get("rejected_legs") or []
            rejected_n = len(rejected) if isinstance(rejected, list) else 0
            is_hold = not order_n and int(consensus.get("min_votes") or 1) <= 1
            discord_notify(
                (
                    f"Proposal · hold · {bucket}"
                    if is_hold
                    else (
                        f"Proposal · {order_n} order(s) · {bucket}"
                        if order_n
                        else f"Proposal · no_consensus · {bucket}"
                    )
                ),
                _format_consensus_body(consensus),
                kind="consensus",
                ok=bool(order_n) or is_hold,
                fields=[
                    {"name": "orders", "value": str(order_n), "inline": True},
                    {"name": "rejected", "value": str(rejected_n), "inline": True},
                    {
                        "name": "mode",
                        "value": "single" if int(consensus.get("min_votes") or 1) <= 1 else f"min≥{consensus.get('min_votes')}",
                        "inline": True,
                    },
                ],
            )
        submit = steps.get("submit") or {}
        if submit:
            if submit.get("skipped") or submit.get("error"):
                reason = str(submit.get("error") or submit.get("reason") or "skipped")
                body = reason
                if reason == "hold":
                    body = f"{body}\n(paired: empty proposal / hold)"
                elif consensus.get("no_consensus"):
                    body = f"{body}\n(paired: no_consensus above)"
                discord_notify(
                    f"Submit · skipped · {bucket}",
                    body,
                    kind="consensus" if reason in ("hold", "no_consensus") else "issue",
                    ok=reason == "hold",
                )
            else:
                body_orders = submit.get("orders") or consensus.get("orders")
                if (
                    isinstance(body_orders, list)
                    and body_orders
                    and isinstance(body_orders[0], dict)
                    and "order" in body_orders[0]
                ):
                    body_orders = [r.get("order") or r for r in body_orders]
                note = submit.get("note") or ""
                body = _summarize_orders(body_orders)
                if note:
                    body = f"{body}\n{note}"
                discord_notify(
                    f"{'Submit · dry-run' if submit.get('dry_run') else 'Submit · paper'} · {bucket}",
                    body,
                    kind="submit",
                    ok=not submit.get("dry_run"),
                )
        discord_notify(
            f"Tick end · {bucket}",
            f"{'error: ' + str(err) if err else 'ok'}",
            kind="issue" if err else "tick_end",
            ok=not err,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[discord] notify skipped: {e}", flush=True)


def copy_fixture_proposals(day: str, hour: int) -> List[str]:
    src = FIXTURES / "hourly" / "proposals"
    dest = hourly_dir(day, hour)
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for aid in active_agent_ids():
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

    day_d, hour, minute, slot, as_of = parse_hour_bucket(args.hour, utc=args.utc)
    day = day_d.isoformat()
    out_dir = hourly_dir(day, slot)
    out_dir.mkdir(parents=True, exist_ok=True)
    bucket = f"{day}T{hour:02d}:{minute:02d}"

    report: Dict[str, Any] = {
        "as_of": as_of,
        "day": day,
        "hour_et": f"{hour:02d}",
        "minute_et": f"{minute:02d}",
        "slot": slot,
        "started_at": _iso_z(),
        "dry_run": not args.submit,
        "steps": {},
    }
    discord_notify(
        f"Tick start · {bucket}",
        f"phase={phase} dry_run={not args.submit}",
        kind="tick_start",
        fields=[
            {"name": "slot", "value": slot, "inline": True},
            {"name": "as_of", "value": as_of, "inline": True},
        ],
    )

    if not args.allow_non_rth and not is_rth_consensus_hour(day_d, hour, minute):
        report["error"] = f"{as_of} outside RTH consensus ticks (09:30–15:30 ET half-hours)"
        _write_json(out_dir / "settle.json", report)
        discord_notify(f"Tick skipped · {bucket}", str(report["error"]), kind="issue", ok=False)
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
                _notify_tick_outcome(bucket, report)
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
                _notify_tick_outcome(bucket, report)
                return report
    else:
        report["steps"]["news"] = {"skipped": True, "path": str(hourly_news_path(day, slot))}

    # --- 2b) Market signals (VIX / bonds / oil) — soft-fail ---
    try:
        from fetch_signals import fetch_signals, write_signals

        sig = fetch_signals(bucket=args.hour)
        wrote = write_signals(sig, bucket=args.hour)
        report["steps"]["signals"] = {
            "wrote": wrote,
            "ok_count": sum(1 for s in (sig.get("signals") or {}).values() if s.get("ok")),
            "errors": sig.get("errors") or {},
        }
    except Exception as e:  # noqa: BLE001
        report["steps"]["signals"] = {"error": str(e), "soft_fail": True}

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
        paths = build_hourly_packs(day, slot, book_path=book_path)
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
        missing = [a for a in active_agent_ids() if not (out_dir / f"{a}.json").exists()]
        report["steps"]["fanout"] = {
            "mode": "placeholder",
            "missing_proposals": missing,
            "note": (
                "Launch one local SDK agent with pack A1.md; write A1.json here. "
                "Re-run with --phase settle (or --skip-ingest --skip-packs --skip-news) after the proposal lands."
            ),
        }

    if phase == "prep":
        ready = {
            "as_of": as_of,
            "day": day,
            "hour_et": f"{hour:02d}",
            "packs": [str(out_dir / f"{a}.md") for a in active_agent_ids()],
            "ready_at": _iso_z(),
            "missing_proposals": missing,
            "next": "Fan out A1 (grok), then: python run_hourly.py --hour … --phase settle",
        }
        _write_json(out_dir / "ready.json", ready)
        report["steps"]["ready"] = ready
        report["phase"] = "prep"
        report["finished_at"] = _iso_z()
        _write_json(out_dir / "settle.json", report)
        _notify_tick_outcome(bucket, report)
        return report

    if (not args.from_fixtures) and missing and not args.allow_missing_proposals:
        report["error"] = "missing proposals (use --phase prep, --from-fixtures, or wait for fan-out)"
        _write_json(out_dir / "settle.json", report)
        _notify_tick_outcome(bucket, report)
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
        "proposals_loaded": consensus.get("proposals_loaded"),
        "min_votes": consensus.get("min_votes"),
        "missing_agents": consensus.get("missing_agents"),
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
    elif not consensus.get("orders"):
        report["steps"]["submit"] = {"skipped": True, "reason": "hold"}
    elif not args.submit:
        from alpaca_client import submit_consensus_orders

        submit_results = submit_consensus_orders(None, consensus["orders"], dry_run=True)
        report["steps"]["submit"] = {
            "dry_run": True,
            "orders": submit_results,
            "note": "dry-run only; omit --dry-run to place Alpaca paper market orders",
        }
    else:
        if not AlpacaClient.credentials_present():
            report["steps"]["submit"] = {"error": "credentials missing; cannot submit"}
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
    _notify_tick_outcome(bucket, report)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Run one hourly Alpaca consensus tick")
    p.add_argument("--hour", required=True, help="Hour bucket YYYY-MM-DDTHH (ET default)")
    p.add_argument("--utc", action="store_true", help="Interpret hour as UTC")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not submit orders (opt-in). Paper submit is ON by default.",
    )
    p.add_argument(
        "--no-submit",
        action="store_true",
        help="Alias for --dry-run.",
    )
    p.add_argument(
        "--submit",
        action="store_true",
        help="Submit consensus orders to Alpaca paper (ON by default; kept for compatibility).",
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

    # Paper submit ON by default; --dry-run / --no-submit opts out.
    if args.dry_run or args.no_submit:
        args.submit = False
    elif not args.submit:
        args.submit = True

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
