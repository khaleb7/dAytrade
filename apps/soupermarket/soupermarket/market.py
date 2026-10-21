"""Read-only Alpaca account and index bars. This module never places an order."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from .clock import to_et


class MarketError(Exception):
    def __init__(self, status: int, what: str) -> None:
        super().__init__(f"{what} HTTP {status}")
        self.status = status
        self.what = what


def _get(url: str, key: str, secret: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
            "User-Agent": "DayTrade/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.loads(res.read().decode())
    except urllib.error.HTTPError as err:
        raise MarketError(int(err.code), "account" if "api.alpaca" in url else "data") from None


def _base(url: str) -> str:
    return url.rstrip("/")


def account(base: str, key: str, secret: str) -> dict[str, Any]:
    row = _get(f"{_base(base)}/v2/account", key, secret)
    return {
        "status": str(row.get("status") or ""),
        "equity": float(row.get("equity") or 0),
        "last_equity": float(row.get("last_equity") or 0),
        "cash": float(row.get("cash") or 0),
    }


def positions(base: str, key: str, secret: str) -> list[dict[str, Any]]:
    rows = _get(f"{_base(base)}/v2/positions", key, secret)
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        qty = float(row.get("qty") or 0)
        if qty <= 0:
            continue
        out.append(
            {
                "symbol": str(row.get("symbol") or "").upper(),
                "qty": qty,
                "price": float(row.get("current_price") or 0),
                "market_value": float(row.get("market_value") or 0),
            }
        )
    return out


def portfolio_history(base: str, key: str, secret: str) -> list[tuple[str, float]]:
    params = urllib.parse.urlencode({"period": "1M", "timeframe": "1D"})
    row = _get(f"{_base(base)}/v2/account/portfolio/history?{params}", key, secret)
    stamps = row.get("timestamp") or []
    equity = row.get("equity") or []
    points: list[tuple[str, float]] = []
    for ts, eq in zip(stamps, equity):
        if eq is None:
            continue
        value = float(eq)
        if not value > 0:
            continue
        day = datetime.fromtimestamp(int(ts), timezone.utc).date().isoformat()
        points.append((day, value))
    return points


def fills(base: str, key: str, secret: str, after: datetime) -> list[dict[str, Any]]:
    token = ""
    rows: list[dict[str, Any]] = []
    while True:
        params = {
            "after": after.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "page_size": "100",
            "direction": "asc",
        }
        if token:
            params["page_token"] = token
        raw = _get(f"{_base(base)}/v2/account/activities/FILL?{urllib.parse.urlencode(params)}", key, secret)
        if not isinstance(raw, list) or not raw:
            break
        rows.extend(raw)
        token = str(raw[-1].get("id") or "")
        if len(raw) < 100 or not token:
            break
    out = []
    for row in rows:
        when = str(row.get("transaction_time") or "")
        qty = float(row.get("qty") or 0)
        price = float(row.get("price") or 0)
        if not when or not qty or not price:
            continue
        et = to_et(datetime.fromisoformat(when.replace("Z", "+00:00")))
        out.append(
            {
                "day": et.date().isoformat(),
                "time": et.strftime("%H:%M"),
                "symbol": str(row.get("symbol") or "").upper(),
                "side": str(row.get("side") or "").lower(),
                "qty": qty,
                "price": price,
                "notional": qty * price,
            }
        )
    return out


def index_closes(data_base: str, key: str, secret: str, start: str) -> dict[str, dict[str, float]]:
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    params = urllib.parse.urlencode(
        {
            "symbols": "SPY,QQQ,DIA",
            "timeframe": "1D",
            "start": f"{start}T00:00:00Z",
            "end": end,
            "feed": "iex",
            "limit": "10000",
            "adjustment": "raw",
        }
    )
    body = _get(f"{_base(data_base)}/v2/stocks/bars?{params}", key, secret)
    bars = body.get("bars") or {}
    closes: dict[str, dict[str, float]] = {}
    for symbol, rows in bars.items():
        series: dict[str, float] = {}
        for row in rows or []:
            day = str(row.get("t") or "")[:10]
            close = row.get("c")
            if day and close is not None and float(close) > 0:
                series[day] = float(close)
        closes[str(symbol).upper()] = series
    return closes
