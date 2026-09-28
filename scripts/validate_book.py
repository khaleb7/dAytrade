"""Validate consensus orders against shared book caps (15% / 35% / 6).

Whole-batch reject on any failure — no partial submit.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import BOOK_PORTFOLIO
from validate_batch import TICKER_RE, equity_at_prices, positions_map, simulate_fills

# Shared book caps (balanced-tier defaults for the single Alpaca account)
CASH_FLOOR_PCT = 15.0
MAX_SINGLE_NAME_PCT = 35.0
MAX_POSITIONS = 6


def load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def check_shared_caps(
    snap: Dict[str, Any],
    prices: Dict[str, float],
    *,
    cash_floor_pct: float = CASH_FLOOR_PCT,
    max_single_name_pct: float = MAX_SINGLE_NAME_PCT,
    max_positions: int = MAX_POSITIONS,
) -> List[str]:
    errors: List[str] = []
    equity = float(snap["equity_usd"])
    cash = float(snap["cash_usd"])
    if equity <= 0:
        return ["post-trade equity must be positive"]

    if cash + 1e-9 < (cash_floor_pct / 100.0) * equity:
        errors.append(
            f"cash floor breached: cash={cash:.4f} < {cash_floor_pct}% of equity={equity:.4f}"
        )

    max_name = max_single_name_pct / 100.0
    for pos in snap["positions"]:
        px = float(prices.get(pos["symbol"], pos.get("mark_price", pos["avg_cost"])))
        mv = float(pos["qty"]) * px
        if mv > max_name * equity + 1e-6:
            errors.append(
                f"max single name breached: {pos['symbol']} mv={mv:.4f} > {max_single_name_pct}% of equity"
            )

    if len(snap["positions"]) > max_positions:
        errors.append(f"max positions breached: {len(snap['positions'])} > {max_positions}")
    return errors


def book_to_portfolio(book: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Alpaca mirror into validate_batch portfolio shape."""
    return {
        "agent_id": "BOOK",
        "cash_usd": float(book.get("cash_usd") or 0),
        "positions": list(book.get("positions") or []),
        "equity_usd": float(book.get("equity_usd") or 0),
        "realized_pnl_usd": float(book.get("realized_pnl_usd") or 0),
    }


def prices_from_book(book: Dict[str, Any], extra: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    prices: Dict[str, float] = {}
    for pos in book.get("positions") or []:
        px = pos.get("mark_price") or pos.get("avg_cost")
        if px:
            prices[pos["symbol"]] = float(px)
    if extra:
        prices.update({k: float(v) for k, v in extra.items()})
    return prices


def validate_book(
    consensus: Dict[str, Any],
    book: Dict[str, Any],
    prices: Optional[Dict[str, float]] = None,
    *,
    cash_floor_pct: float = CASH_FLOOR_PCT,
    max_single_name_pct: float = MAX_SINGLE_NAME_PCT,
    max_positions: int = MAX_POSITIONS,
    apply_sizing_offset: bool = True,
    equity_offset: Optional[float] = None,
) -> Dict[str, Any]:
    """Return {ok, errors, post_trade}. Empty consensus orders → ok hold.

    By default applies state/alpaca/config.json equity_offset_usd (-99000) so
    caps/affordability run on the ~$1000 sizing book, not raw $100k paper equity.
    """
    from alpaca_client import sizing_book

    work = sizing_book(book, offset=equity_offset) if apply_sizing_offset else book
    errors: List[str] = []
    orders = consensus.get("orders") or []
    if not isinstance(orders, list):
        return {"ok": False, "errors": ["consensus.orders must be an array"], "post_trade": None}

    # Strip consensus metadata fields for simulate_fills
    clean_orders: List[Dict[str, Any]] = []
    for i, o in enumerate(orders):
        if not isinstance(o, dict):
            errors.append(f"orders[{i}]: not an object")
            continue
        side = o.get("side")
        symbol = o.get("symbol")
        if side not in ("buy", "sell"):
            errors.append(f"orders[{i}]: side must be buy|sell")
            continue
        if not isinstance(symbol, str) or not TICKER_RE.match(symbol.upper()):
            errors.append(f"orders[{i}]: invalid symbol {symbol!r}")
            continue
        entry: Dict[str, Any] = {"side": side, "symbol": symbol.upper()}
        if side == "buy":
            entry["notional_usd"] = o.get("notional_usd")
        else:
            entry["qty"] = o.get("qty")
        clean_orders.append(entry)

    if errors:
        return {"ok": False, "errors": errors, "post_trade": None}

    if not clean_orders:
        port = book_to_portfolio(work)
        return {
            "ok": True,
            "errors": [],
            "post_trade": {
                "cash_usd": port["cash_usd"],
                "positions": port["positions"],
                "equity_usd": port.get("equity_usd")
                or equity_at_prices(
                    port["cash_usd"], positions_map(port), prices_from_book(work, prices)
                ),
            },
            "hold": True,
            "sizing_view": bool(work.get("sizing_view")),
            "equity_offset_usd": work.get("equity_offset_usd"),
        }

    px = prices_from_book(work, prices)
    # For buys of new symbols, require a price hint
    for o in clean_orders:
        if o["symbol"] not in px:
            errors.append(f"no mark/price for {o['symbol']} (pass --prices or mark in book)")
    if errors:
        return {"ok": False, "errors": errors, "post_trade": None}

    portfolio = book_to_portfolio(work)
    snap, fill_errors = simulate_fills(portfolio, clean_orders, px)
    errors.extend(fill_errors)
    if errors or snap is None:
        return {"ok": False, "errors": errors, "post_trade": None}

    errors.extend(
        check_shared_caps(
            snap,
            px,
            cash_floor_pct=cash_floor_pct,
            max_single_name_pct=max_single_name_pct,
            max_positions=max_positions,
        )
    )
    if errors:
        return {
            "ok": False,
            "errors": errors,
            "post_trade": None,
            "sizing_view": True,
            "equity_offset_usd": work.get("equity_offset_usd"),
        }

    return {
        "ok": True,
        "errors": [],
        "post_trade": {
            "cash_usd": snap["cash_usd"],
            "positions": snap["positions"],
            "equity_usd": snap["equity_usd"],
            "realized_pnl_usd": snap["realized_pnl_usd"],
        },
        "sizing_view": bool(work.get("sizing_view")),
        "equity_offset_usd": work.get("equity_offset_usd"),
        "broker_cash_usd": work.get("broker_cash_usd"),
        "broker_equity_usd": work.get("broker_equity_usd"),
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Validate consensus vs shared book caps")
    p.add_argument("consensus", type=Path, help="consensus.json path")
    p.add_argument("--book", type=Path, default=BOOK_PORTFOLIO)
    p.add_argument("--prices", type=Path, help="JSON {symbol: price} for marks")
    p.add_argument("--cash-floor", type=float, default=CASH_FLOOR_PCT)
    p.add_argument("--max-name", type=float, default=MAX_SINGLE_NAME_PCT)
    p.add_argument("--max-positions", type=int, default=MAX_POSITIONS)
    p.add_argument(
        "--no-sizing-offset",
        action="store_true",
        help="Validate against raw broker cash/equity (skip equity_offset_usd)",
    )
    p.add_argument("--equity-offset", type=float, default=None, help="Override equity_offset_usd")
    args = p.parse_args(argv)

    consensus = load_json(args.consensus)
    book = load_json(args.book) if args.book.exists() else {"cash_usd": 1000.0, "positions": [], "equity_usd": 1000.0}
    prices = load_json(args.prices) if args.prices else None
    result = validate_book(
        consensus,
        book,
        prices,
        cash_floor_pct=args.cash_floor,
        max_single_name_pct=args.max_name,
        max_positions=args.max_positions,
        apply_sizing_offset=not args.no_sizing_offset,
        equity_offset=args.equity_offset,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
