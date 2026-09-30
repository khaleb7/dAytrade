"""Validate a trade batch against tier rules. Reject whole batch on any failure."""
from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from paths import ROSTER, portfolio_path

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
FORBIDDEN_MARKERS = ("/", "USD", "USDT", "-P", "-C", "BTC", "ETH")
# Signal-only / non-equity instruments — never accept in proposals or consensus submits.
SIGNAL_ONLY_BLOCKLIST = frozenset(
    {
        "VIX",
        "VXX",
        "UVXY",
        "UVIX",
        "SVIX",
        "SVXY",
        "VIXY",
        "VIXM",
        "VXZ",
        "TVIX",
    }
)
AGENT_IDS = {"A1", "A2", "A3", "A4", "A5"}


def is_signal_only_symbol(symbol: str) -> bool:
    up = symbol.upper().strip()
    if up in SIGNAL_ONLY_BLOCKLIST:
        return True
    # Futures / continuous contracts (CL=F, ES=F, …) and index caret forms
    if "=" in up or up.startswith("^"):
        return True
    return False


def load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def load_roster(roster_path: Path = ROSTER) -> Dict[str, Any]:
    return load_json(roster_path)


def load_portfolio(agent_id: str, path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or portfolio_path(agent_id)
    return load_json(p)


def positions_map(portfolio: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {p["symbol"]: dict(p) for p in portfolio.get("positions", [])}


def equity_at_prices(
    cash: float, positions: Dict[str, Dict[str, Any]], prices: Dict[str, float]
) -> float:
    total = cash
    for sym, pos in positions.items():
        px = prices.get(sym, pos.get("mark_price", pos.get("avg_cost", 0.0)))
        total += float(pos["qty"]) * float(px)
    return total


def simulate_fills(
    portfolio: Dict[str, Any],
    orders: List[Dict[str, Any]],
    opens: Dict[str, float],
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Return (post_trade_snapshot, errors). Snapshot used only for rule checks / settle."""
    errors: List[str] = []
    cash = float(portfolio["cash_usd"])
    pos = positions_map(portfolio)
    realized = float(portfolio.get("realized_pnl_usd", 0.0))

    for i, order in enumerate(orders):
        side = order.get("side")
        symbol = order.get("symbol")
        if side not in ("buy", "sell"):
            errors.append(f"orders[{i}]: side must be buy|sell")
            continue
        if not isinstance(symbol, str) or not TICKER_RE.match(symbol):
            errors.append(f"orders[{i}]: invalid symbol {symbol!r}")
            continue
        up = symbol.upper()
        if is_signal_only_symbol(up):
            errors.append(
                f"orders[{i}]: {symbol} is signal-only / non-tradeable (VIX/vol products and futures blocked)"
            )
            continue
        if any(m in up for m in FORBIDDEN_MARKERS) and up not in ("SPY", "QQQ", "IWM", "DIA"):
            # crude crypto/options guard; allow common ETFs
            if "BTC" in up or "ETH" in up or up.endswith("-P") or up.endswith("-C"):
                errors.append(f"orders[{i}]: forbidden instrument {symbol}")
                continue
        if symbol not in opens:
            errors.append(f"orders[{i}]: no open price for {symbol}")
            continue
        px = float(opens[symbol])
        if px <= 0:
            errors.append(f"orders[{i}]: non-positive open for {symbol}")
            continue

        if side == "buy":
            if "qty" in order and order.get("notional_usd") is None:
                errors.append(f"orders[{i}]: buys must use notional_usd")
                continue
            notional = order.get("notional_usd")
            if not isinstance(notional, (int, float)) or notional <= 0:
                errors.append(f"orders[{i}]: notional_usd must be > 0")
                continue
            notional = float(notional)
            if notional > cash + 1e-9:
                errors.append(f"orders[{i}]: insufficient cash for buy {symbol}")
                continue
            qty = notional / px
            cash -= notional
            if symbol in pos:
                old = pos[symbol]
                new_qty = float(old["qty"]) + qty
                new_cost = float(old["avg_cost"]) * float(old["qty"]) + notional
                pos[symbol] = {
                    "symbol": symbol,
                    "qty": new_qty,
                    "avg_cost": new_cost / new_qty,
                    "mark_price": px,
                }
            else:
                pos[symbol] = {
                    "symbol": symbol,
                    "qty": qty,
                    "avg_cost": px,
                    "mark_price": px,
                }
        else:  # sell
            if "notional_usd" in order and order.get("qty") is None:
                errors.append(f"orders[{i}]: sells must use qty")
                continue
            qty = order.get("qty")
            if not isinstance(qty, (int, float)) or qty <= 0:
                errors.append(f"orders[{i}]: qty must be > 0")
                continue
            qty = float(qty)
            if symbol not in pos:
                errors.append(f"orders[{i}]: cannot sell unheld {symbol}")
                continue
            held = float(pos[symbol]["qty"])
            if qty > held + 1e-9:
                errors.append(f"orders[{i}]: sell qty {qty} > held {held}")
                continue
            proceeds = qty * px
            avg = float(pos[symbol]["avg_cost"])
            realized += (px - avg) * qty
            cash += proceeds
            rem = held - qty
            if rem <= 1e-12:
                del pos[symbol]
            else:
                pos[symbol] = {
                    "symbol": symbol,
                    "qty": rem,
                    "avg_cost": avg,
                    "mark_price": px,
                }

    if errors:
        return None, errors

    eq = equity_at_prices(cash, pos, opens)
    snap = {
        "cash_usd": cash,
        "positions": list(pos.values()),
        "equity_usd": eq,
        "realized_pnl_usd": realized,
        "positions_map": pos,
    }
    return snap, []


def check_tier_rules(
    agent_id: str,
    snap: Dict[str, Any],
    opens: Dict[str, float],
    roster: Dict[str, Any],
) -> List[str]:
    rules = roster["agents"][agent_id]
    errors: List[str] = []
    equity = float(snap["equity_usd"])
    cash = float(snap["cash_usd"])
    if equity <= 0:
        errors.append("post-trade equity must be positive")
        return errors

    cash_floor = rules["cash_floor_pct"] / 100.0
    if cash + 1e-9 < cash_floor * equity:
        errors.append(
            f"cash floor breached: cash={cash:.4f} < {rules['cash_floor_pct']}% of equity={equity:.4f}"
        )

    max_name = rules["max_single_name_pct"] / 100.0
    for pos in snap["positions"]:
        px = float(opens.get(pos["symbol"], pos.get("mark_price", pos["avg_cost"])))
        mv = float(pos["qty"]) * px
        if mv > max_name * equity + 1e-6:
            errors.append(
                f"max single name breached: {pos['symbol']} mv={mv:.4f} > {rules['max_single_name_pct']}% of equity"
            )

    if len(snap["positions"]) > int(rules["max_positions"]):
        errors.append(
            f"max positions breached: {len(snap['positions'])} > {rules['max_positions']}"
        )
    return errors


def validate_batch(
    batch: Dict[str, Any],
    portfolio: Dict[str, Any],
    opens: Dict[str, float],
    roster: Optional[Dict[str, Any]] = None,
    expected_as_of: Optional[str] = None,
) -> Dict[str, Any]:
    """Return {ok, errors, post_trade}."""
    roster = roster or load_roster()
    errors: List[str] = []

    if not isinstance(batch, dict):
        return {"ok": False, "errors": ["batch must be an object"], "post_trade": None}

    agent_id = batch.get("agent_id")
    if agent_id not in AGENT_IDS:
        errors.append(f"invalid agent_id {agent_id!r}")
    elif agent_id not in roster.get("agents", {}):
        errors.append(f"agent_id {agent_id} not in roster")

    as_of = batch.get("as_of")
    if not isinstance(as_of, str) or len(as_of) != 10:
        errors.append("as_of must be YYYY-MM-DD")
    if expected_as_of and as_of != expected_as_of:
        errors.append(f"as_of {as_of} != expected {expected_as_of}")
    if portfolio.get("agent_id") and agent_id and portfolio["agent_id"] != agent_id:
        errors.append("batch agent_id does not match portfolio")

    thesis = batch.get("thesis")
    if not isinstance(thesis, str) or not thesis.strip():
        errors.append("thesis must be a non-empty string")

    orders = batch.get("orders")
    if not isinstance(orders, list):
        errors.append("orders must be an array")
        orders = []

    if errors:
        return {"ok": False, "errors": errors, "post_trade": None}

    snap, fill_errors = simulate_fills(portfolio, orders, opens)
    errors.extend(fill_errors)
    if errors or snap is None:
        return {"ok": False, "errors": errors, "post_trade": None}

    errors.extend(check_tier_rules(agent_id, snap, opens, roster))
    if errors:
        return {"ok": False, "errors": errors, "post_trade": None}

    post = {
        "cash_usd": snap["cash_usd"],
        "positions": snap["positions"],
        "equity_usd": snap["equity_usd"],
        "realized_pnl_usd": snap["realized_pnl_usd"],
    }
    return {"ok": True, "errors": [], "post_trade": post}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Validate a DayTrade batch (whole-batch reject)")
    p.add_argument("batch", type=Path, help="Path to batch JSON")
    p.add_argument("--portfolio", type=Path, help="Portfolio JSON (default from agent_id)")
    p.add_argument("--market", type=Path, required=True, help="Market day JSON with opens")
    p.add_argument("--as-of", dest="as_of", help="Expected trading day")
    p.add_argument("--roster", type=Path, default=ROSTER)
    args = p.parse_args(argv)

    batch = load_json(args.batch)
    roster = load_json(args.roster)
    market = load_json(args.market)
    opens = {k: float(v["open"]) for k, v in market.get("bars", market.get("quotes", {})).items()}
    # also allow flat {symbol: {open, close}}
    if not opens and "symbols" in market:
        opens = {k: float(v["open"]) for k, v in market["symbols"].items()}

    agent_id = batch.get("agent_id", "A1")
    port_path = args.portfolio or portfolio_path(agent_id)
    portfolio = load_json(port_path)

    result = validate_batch(batch, portfolio, opens, roster, expected_as_of=args.as_of)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
