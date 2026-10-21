"""Assemble the day recap from read-only market data."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .clock import to_et
from .config import Config
from .market import MarketError, account, fills, index_closes, portfolio_history, positions
from .page import render, render_error

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"at": 0.0, "html": ""}

_COLORS = {
    "Account": "#1c3d5a",
    "SPY": "#2f6f4e",
    "QQQ": "#8a5a12",
    "DIA": "#6b3a4a",
}


def _rebase(points: list[tuple[str, float]]) -> tuple[list[str], list[float], float]:
    base = points[0][1]
    dates = [day for day, _ in points]
    values = [1000.0 * value / base for _, value in points]
    return dates, values, values[-1] / 10.0 - 100.0


def build_view(cfg: Config) -> dict[str, Any]:
    if not cfg.alpaca_key or not cfg.alpaca_secret:
        raise MarketError(0, "keys")
    book = account(cfg.alpaca_base, cfg.alpaca_key, cfg.alpaca_secret)
    held = positions(cfg.alpaca_base, cfg.alpaca_key, cfg.alpaca_secret)
    history = portfolio_history(cfg.alpaca_base, cfg.alpaca_key, cfg.alpaca_secret)
    today_et = to_et(datetime.now(timezone.utc)).date().isoformat()
    if history and book["equity"] > 0:
        if history[-1][0] == today_et:
            history[-1] = (today_et, book["equity"])
        elif history[-1][0] < today_et:
            history.append((today_et, book["equity"]))
    if len(history) < 2:
        raise MarketError(0, "history")
    start = history[0][0]
    after = datetime.fromisoformat(start).replace(tzinfo=timezone.utc) - timedelta(days=1)
    trade_rows = fills(cfg.alpaca_base, cfg.alpaca_key, cfg.alpaca_secret, after)
    closes = index_closes(cfg.alpaca_data, cfg.alpaca_key, cfg.alpaca_secret, start)

    dates, account_values, account_pct = _rebase(history)
    series: dict[str, list[float]] = {"Account": account_values}
    ending: list[tuple[str, str, float, float]] = [
        ("Account", _COLORS["Account"], account_values[-1], account_pct)
    ]
    for symbol in ("SPY", "QQQ", "DIA"):
        by_day = closes.get(symbol) or {}
        raw: list[float | None] = []
        last: float | None = None
        for day in dates:
            if day in by_day:
                last = by_day[day]
            raw.append(last)
        known = next((value for value in raw if value is not None), None)
        if known is None:
            continue
        filled = [known if value is None else value for value in raw]
        base = filled[0]
        values = [1000.0 * value / base for value in filled]
        series[symbol] = values
        ending.append((symbol, _COLORS[symbol], values[-1], values[-1] / 10.0 - 100.0))

    today = today_et
    days = sorted({row["day"] for row in trade_rows})
    session = today if today in days else (days[-1] if days else today)
    session_trades = [row for row in trade_rows if row["day"] == session]
    stamp = datetime.fromisoformat(session)
    label_day = f"{stamp.strftime('%A, %B')} {stamp.day}, {stamp.year}"
    if session != today:
        label_day = f"Last session, {label_day}"
    last_eq = book["last_equity"]
    day_change = book["equity"] - last_eq if last_eq > 0 else 0.0
    day_pct = (day_change / last_eq * 100.0) if last_eq > 0 else 0.0
    return {
        "day_label": label_day,
        "equity": book["equity"],
        "last_equity": last_eq,
        "day_change": day_change,
        "day_change_pct": day_pct,
        "cash": book["cash"],
        "status": book["status"] or "account",
        "positions": held,
        "trades": session_trades,
        "dates": dates,
        "series": series,
        "ending": ending,
        "start": start,
    }


def page(cfg: Config) -> str:
    now = time.monotonic()
    with _LOCK:
        if _CACHE["html"] and now - float(_CACHE["at"]) < 45:
            return str(_CACHE["html"])
    try:
        html = render(build_view(cfg))
    except MarketError as err:
        if err.what == "keys":
            html = render_error("Alpaca keys are not configured.")
        else:
            html = render_error(f"Could not read the {err.what} feed ({err.status}).")
    except Exception:
        html = render_error("Could not build the recap.")
    else:
        with _LOCK:
            _CACHE["at"] = time.monotonic()
            _CACHE["html"] = html
    return html
