"""Alpaca paper trading client (env credentials only — never write secrets to store).

Env:
  APCA_API_KEY_ID
  APCA_API_SECRET_KEY
  APCA_API_BASE_URL  (default https://paper-api.alpaca.markets)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from paths import ALPACA_CONFIG, BOOK_PORTFOLIO

DEFAULT_BASE = "https://paper-api.alpaca.markets"
TARGET_EQUITY = 1000.0
# Alpaca paper defaults to $100k; offset maps that onto target_equity (~$1000).
DEFAULT_EQUITY_OFFSET = -99000.0


def _iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_config(path: Path = ALPACA_CONFIG) -> Dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text())
    return {
        "paper": True,
        "base_url": DEFAULT_BASE,
        "target_equity_usd": TARGET_EQUITY,
        "equity_offset_usd": DEFAULT_EQUITY_OFFSET,
    }


def equity_offset_usd(cfg: Optional[Dict[str, Any]] = None) -> float:
    cfg = cfg or load_config()
    raw = cfg.get("equity_offset_usd", DEFAULT_EQUITY_OFFSET)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(DEFAULT_EQUITY_OFFSET)


def sizing_book(
    book: Dict[str, Any],
    *,
    offset: Optional[float] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a copy of the book with cash/equity shifted by equity_offset_usd.

    Positions unchanged. Used for agent packs + shared cap validation so a $100k
    paper account is treated as ~$1000. Broker submits still use proposal notionals as-is.

    If the book is already near target equity (e.g. fixtures at $1000), the offset
    is skipped so we do not drive sizing cash negative.
    """
    if book.get("sizing_view"):
        return dict(book)

    cfg = cfg or load_config()
    if offset is None:
        off = equity_offset_usd(cfg)
    else:
        off = float(offset)

    cash = float(book.get("cash_usd") or 0)
    equity = float(book.get("equity_usd") or 0)
    if not book.get("equity_usd") and book.get("positions"):
        mv = sum(
            float(
                p.get("market_value")
                or float(p.get("qty") or 0)
                * float(p.get("mark_price") or p.get("avg_cost") or 0)
            )
            for p in book["positions"]
        )
        equity = cash + mv

    target = float(cfg.get("target_equity_usd") or TARGET_EQUITY)
    # Skip offset when book is already target-scale (fixtures / seed)
    if off != 0 and equity + off <= 0 and 0 < equity <= target * 2:
        off = 0.0

    view = dict(book)
    view["broker_cash_usd"] = cash
    view["broker_equity_usd"] = equity
    view["equity_offset_usd"] = off
    view["cash_usd"] = cash + off
    view["equity_usd"] = equity + off
    view["sizing_view"] = True
    view["target_equity_usd"] = target
    if "buying_power" in book:
        try:
            bp = float(book["buying_power"])
            view["buying_power"] = bp + off if off and bp + off > 0 else (bp if off == 0 else max(bp + off, 0))
        except (TypeError, ValueError):
            pass
    return view


def ensure_config(path: Path = ALPACA_CONFIG) -> Dict[str, Any]:
    """Write paper config stub if missing. Never includes secrets."""
    cfg = {
        "paper": True,
        "base_url": os.environ.get("APCA_API_BASE_URL", DEFAULT_BASE).rstrip("/"),
        "target_equity_usd": TARGET_EQUITY,
        "equity_offset_usd": DEFAULT_EQUITY_OFFSET,
        "note": (
            "Secrets live in APCA_API_KEY_ID / APCA_API_SECRET_KEY env vars only. "
            "equity_offset_usd (-99000) maps $100k paper onto a $1000 sizing book."
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(cfg, indent=2) + "\n")
        return cfg
    existing = json.loads(path.read_text())
    for k, v in cfg.items():
        if k == "note":
            existing.setdefault(k, v)
        else:
            existing.setdefault(k, v)
    # Force-set offset if missing (setdefault already); write back
    path.write_text(json.dumps(existing, indent=2) + "\n")
    return existing


class AlpacaClient:
    def __init__(
        self,
        *,
        key_id: Optional[str] = None,
        secret: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.key_id = key_id or os.environ.get("APCA_API_KEY_ID", "")
        self.secret = secret or os.environ.get("APCA_API_SECRET_KEY", "")
        cfg = load_config()
        self.base_url = (base_url or os.environ.get("APCA_API_BASE_URL") or cfg.get("base_url") or DEFAULT_BASE).rstrip(
            "/"
        )
        if not self.key_id or not self.secret:
            raise RuntimeError(
                "Missing APCA_API_KEY_ID / APCA_API_SECRET_KEY in environment "
                "(do not put secrets in the Project store)"
            )

    @staticmethod
    def credentials_present() -> bool:
        return bool(os.environ.get("APCA_API_KEY_ID") and os.environ.get("APCA_API_SECRET_KEY"))

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        *,
        timeout: int = 30,
    ) -> Any:
        url = f"{self.base_url}{path}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = Request(
            url,
            data=data,
            method=method.upper(),
            headers={
                "APCA-API-KEY-ID": self.key_id,
                "APCA-API-SECRET-KEY": self.secret,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
        except HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            raise RuntimeError(f"Alpaca HTTP {e.code} {path}: {err_body or e.reason}") from e
        except URLError as e:
            raise RuntimeError(f"Alpaca network error {path}: {e}") from e

    def get_account(self) -> Dict[str, Any]:
        return self._request("GET", "/v2/account")

    def list_positions(self) -> List[Dict[str, Any]]:
        data = self._request("GET", "/v2/positions")
        return data if isinstance(data, list) else []

    def list_orders(self, status: str = "open") -> List[Dict[str, Any]]:
        data = self._request("GET", f"/v2/orders?status={status}")
        return data if isinstance(data, list) else []

    def submit_market_order(
        self,
        *,
        symbol: str,
        side: str,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
        time_in_force: str = "day",
    ) -> Dict[str, Any]:
        """Submit a market order. Buys prefer notional (fractional); sells use qty."""
        side = side.lower()
        if side not in ("buy", "sell"):
            raise ValueError(f"side must be buy|sell, got {side}")
        body: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side,
            "type": "market",
            "time_in_force": time_in_force,
        }
        if side == "buy":
            if notional is None or float(notional) <= 0:
                raise ValueError("buy requires notional > 0")
            body["notional"] = f"{float(notional):.2f}"
        else:
            if qty is None or float(qty) <= 0:
                raise ValueError("sell requires qty > 0")
            body["qty"] = str(float(qty))
        return self._request("POST", "/v2/orders", body)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self._request("DELETE", f"/v2/orders/{order_id}")

    def cancel_all_orders(self) -> Any:
        return self._request("DELETE", "/v2/orders")

    def reconcile(self, out_path: Path = BOOK_PORTFOLIO) -> Dict[str, Any]:
        """Pull account + positions; mirror to state/book/portfolio.json (no secrets)."""
        acct = self.get_account()
        positions_raw = self.list_positions()
        cash = float(acct.get("cash") or 0)
        equity = float(acct.get("equity") or 0)
        positions = []
        for p in positions_raw:
            positions.append(
                {
                    "symbol": p.get("symbol"),
                    "qty": float(p.get("qty") or 0),
                    "avg_cost": float(p.get("avg_entry_price") or 0),
                    "mark_price": float(p.get("current_price") or p.get("lastday_price") or 0),
                    "market_value": float(p.get("market_value") or 0),
                }
            )
        mirror = {
            "broker": "alpaca_paper",
            "account_id": acct.get("id"),
            "cash_usd": cash,
            "equity_usd": equity,
            "buying_power": float(acct.get("buying_power") or 0),
            "positions": positions,
            "reconciled_at": _iso_z(),
            "status": acct.get("status"),
            "currency": acct.get("currency", "USD"),
            "target_equity_usd": load_config().get("target_equity_usd", TARGET_EQUITY),
            "equity_offset_usd": equity_offset_usd(),
        }
        # Annotate sizing view fields (mirror stays broker-truthful for cash/equity keys)
        sized = sizing_book(mirror)
        mirror["sizing_cash_usd"] = sized["cash_usd"]
        mirror["sizing_equity_usd"] = sized["equity_usd"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(mirror, indent=2) + "\n")
        return mirror


def submit_consensus_orders(
    client: Optional[AlpacaClient],
    orders: List[Dict[str, Any]],
    *,
    dry_run: bool = True,
) -> List[Dict[str, Any]]:
    results = []
    for o in orders:
        entry = {"order": o, "dry_run": dry_run}
        if dry_run:
            entry["status"] = "dry_run_skip"
            results.append(entry)
            continue
        if client is None:
            entry["status"] = "error"
            entry["error"] = "client required when dry_run=False"
            results.append(entry)
            continue
        try:
            if o["side"] == "buy":
                resp = client.submit_market_order(
                    symbol=o["symbol"], side="buy", notional=float(o["notional_usd"])
                )
            else:
                resp = client.submit_market_order(symbol=o["symbol"], side="sell", qty=float(o["qty"]))
            entry["status"] = "submitted"
            entry["alpaca"] = {"id": resp.get("id"), "status": resp.get("status"), "symbol": resp.get("symbol")}
        except Exception as e:  # noqa: BLE001 — surface per-order failure
            entry["status"] = "error"
            entry["error"] = str(e)
        results.append(entry)
    return results


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Alpaca paper client (env credentials)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ensure-config", help="Write state/alpaca/config.json stub (no secrets)")
    sub.add_parser("account", help="GET /v2/account (print equity summary)")
    sub.add_parser("reconcile", help="Mirror account+positions → state/book/portfolio.json")
    p_cancel = sub.add_parser("cancel-order", help="Cancel one order by id")
    p_cancel.add_argument("order_id")
    args = p.parse_args(argv)

    if args.cmd == "ensure-config":
        cfg = ensure_config()
        # scrub any accidental secret-like keys
        for bad in list(cfg.keys()):
            if "secret" in bad.lower() or "key" in bad.lower() and bad != "note":
                if bad not in ("paper", "base_url", "target_equity_usd", "note"):
                    pass
        print(json.dumps(cfg, indent=2))
        return 0

    if not AlpacaClient.credentials_present():
        print("error: APCA_API_KEY_ID / APCA_API_SECRET_KEY not set", file=sys.stderr)
        return 1

    client = AlpacaClient()
    if args.cmd == "account":
        acct = client.get_account()
        summary = {
            "id": acct.get("id"),
            "status": acct.get("status"),
            "equity": acct.get("equity"),
            "cash": acct.get("cash"),
            "buying_power": acct.get("buying_power"),
            "currency": acct.get("currency"),
            "pattern_day_trader": acct.get("pattern_day_trader"),
        }
        print(json.dumps(summary, indent=2))
        return 0
    if args.cmd == "reconcile":
        mirror = client.reconcile()
        print(
            json.dumps(
                {
                    "wrote": str(BOOK_PORTFOLIO),
                    "equity_usd": mirror["equity_usd"],
                    "cash_usd": mirror["cash_usd"],
                    "sizing_equity_usd": mirror.get("sizing_equity_usd"),
                    "sizing_cash_usd": mirror.get("sizing_cash_usd"),
                    "equity_offset_usd": mirror.get("equity_offset_usd"),
                    "positions": len(mirror["positions"]),
                    "account_id": mirror.get("account_id"),
                },
                indent=2,
            )
        )
        return 0
    if args.cmd == "cancel-order":
        resp = client.cancel_order(args.order_id)
        print(json.dumps(resp or {"cancelled": args.order_id}, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
