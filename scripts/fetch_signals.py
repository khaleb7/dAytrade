"""Fetch/cache market **signals** for RTH packs (VIX, bonds, oil).

Signal-only — not a tradeable universe. Soft-fail: network/yfinance errors
return a stub payload and never abort the tick.

Sources (Yahoo Finance via yfinance, same stack as fetch_market.py):
  - VIX:  ^VIX
  - Bonds: ^TNX (US 10Y yield %), TLT (20Y+ Treasury ETF), ^IRX (13-week T-bill %; short-rate proxy)
  - Oil:   CL=F (WTI front), USO (ETF proxy)

Cache:
  state/signals/latest.json
  state/hourly/YYYY-MM-DD/HHMM/signals.json  (when --bucket given)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from paths import STATE, hourly_dir

SIGNALS = STATE / "signals"
LATEST = SIGNALS / "latest.json"

# Yahoo tickers → pack field metadata
SIGNAL_SPECS: List[Dict[str, str]] = [
    {"id": "vix", "yahoo": "^VIX", "label": "VIX", "unit": "index", "group": "vol"},
    {"id": "us10y", "yahoo": "^TNX", "label": "US 10Y yield", "unit": "pct", "group": "bonds"},
    {"id": "us_tbill_13w", "yahoo": "^IRX", "label": "US 13W T-bill", "unit": "pct", "group": "bonds"},
    {"id": "tlt", "yahoo": "TLT", "label": "TLT", "unit": "usd", "group": "bonds"},
    {"id": "wti", "yahoo": "CL=F", "label": "WTI crude", "unit": "usd", "group": "oil"},
    {"id": "uso", "yahoo": "USO", "label": "USO", "unit": "usd", "group": "oil"},
]


def _iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pct_change(last: Optional[float], prev: Optional[float]) -> Optional[float]:
    if last is None or prev is None or prev == 0:
        return None
    return round((last - prev) / abs(prev) * 100.0, 4)


def _abs_change(last: Optional[float], prev: Optional[float]) -> Optional[float]:
    if last is None or prev is None:
        return None
    return round(last - prev, 6)


def _fetch_one(yahoo: str) -> Tuple[Optional[float], Optional[float], Optional[str], Optional[str]]:
    """Return (last, prev_close, as_of_iso, error)."""
    try:
        import yfinance as yf
    except Exception as e:  # noqa: BLE001
        return None, None, None, f"yfinance import failed: {e}"

    try:
        t = yf.Ticker(yahoo)
        # Prefer recent daily history (2–5 sessions) for last + prior close
        hist = t.history(period="5d", auto_adjust=True)
        last = None
        prev = None
        as_of = None
        if hist is not None and not hist.empty:
            closes = hist["Close"].dropna()
            if len(closes) >= 1:
                last = float(closes.iloc[-1])
                as_of = closes.index[-1].to_pydatetime().astimezone(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            if len(closes) >= 2:
                prev = float(closes.iloc[-2])
        if last is None:
            # fast_info fallback
            try:
                fi = getattr(t, "fast_info", None) or {}
                last = float(fi.get("last_price") or fi.get("regular_market_price") or 0) or None
                prev = float(fi.get("previous_close") or 0) or None
                if last:
                    as_of = _iso_z()
            except Exception:  # noqa: BLE001
                pass
        if last is None:
            return None, None, None, "no price"
        return last, prev, as_of or _iso_z(), None
    except Exception as e:  # noqa: BLE001
        return None, None, None, str(e)


def fetch_signals(*, bucket: Optional[str] = None) -> Dict[str, Any]:
    """Fetch all signal specs; never raises for upstream failures."""
    items: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    for spec in SIGNAL_SPECS:
        last, prev, as_of, err = _fetch_one(spec["yahoo"])
        if err and last is None:
            errors[spec["id"]] = err
            items[spec["id"]] = {
                "label": spec["label"],
                "yahoo": spec["yahoo"],
                "group": spec["group"],
                "unit": spec["unit"],
                "level": None,
                "change": None,
                "change_pct": None,
                "as_of": None,
                "ok": False,
                "error": err,
            }
            continue
        items[spec["id"]] = {
            "label": spec["label"],
            "yahoo": spec["yahoo"],
            "group": spec["group"],
            "unit": spec["unit"],
            "level": None if last is None else round(last, 6),
            "change": _abs_change(last, prev),
            "change_pct": _pct_change(last, prev),
            "as_of": as_of,
            "ok": last is not None,
            "error": err,
        }

    payload: Dict[str, Any] = {
        "fetched_at": _iso_z(),
        "source": "yfinance",
        "note": (
            "Signal-only context for agent packs. "
            "VIX/VXX/UVXY and futures are not tradeable. "
            "TLT/USO remain normal US ETFs under existing book rules if agents propose them."
        ),
        "signals": items,
        "compact": _compact_text(items),
        "errors": errors,
        "bucket": bucket,
    }
    return payload


def _fmt_level(item: Dict[str, Any]) -> str:
    lv = item.get("level")
    if lv is None:
        return "n/a"
    unit = item.get("unit")
    if unit == "pct":
        return f"{lv:.3f}%"
    if unit == "index":
        return f"{lv:.2f}"
    return f"{lv:.2f}"


def _fmt_chg(item: Dict[str, Any]) -> str:
    ch = item.get("change")
    pct = item.get("change_pct")
    if ch is None and pct is None:
        return "n/a"
    parts = []
    if ch is not None:
        sign = "+" if ch >= 0 else ""
        unit = item.get("unit")
        if unit == "pct":
            parts.append(f"{sign}{ch:.3f}pt")
        else:
            parts.append(f"{sign}{ch:.2f}")
    if pct is not None:
        sign = "+" if pct >= 0 else ""
        parts.append(f"{sign}{pct:.2f}%")
    return " / ".join(parts)


def _compact_text(items: Dict[str, Any]) -> str:
    """One compact multi-line block for pack injection."""
    lines = [
        "Market signals (context only — do not trade VIX/vol products or futures; "
        "TLT/USO OK only as normal US ETFs under shared book rules):",
    ]
    order = ["vix", "us10y", "us_tbill_13w", "tlt", "wti", "uso"]
    for sid in order:
        it = items.get(sid) or {}
        label = it.get("label") or sid
        if not it.get("ok"):
            lines.append(f"- {label}: unavailable ({it.get('error') or 'missing'})")
            continue
        as_of = it.get("as_of") or "?"
        lines.append(
            f"- {label}: {_fmt_level(it)}  Δ {_fmt_chg(it)}  as_of={as_of}"
        )
    return "\n".join(lines)


def write_signals(payload: Dict[str, Any], *, bucket: Optional[str] = None) -> Dict[str, str]:
    SIGNALS.mkdir(parents=True, exist_ok=True)
    LATEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    wrote = {"latest": str(LATEST)}
    if bucket:
        try:
            from hour_bucket import parse_hour_bucket

            day, _h, _m, slot, _as_of = parse_hour_bucket(bucket)
            out = hourly_dir(day.isoformat(), slot) / "signals.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            wrote["hourly"] = str(out)
        except Exception as e:  # noqa: BLE001
            wrote["hourly_error"] = str(e)
    return wrote


def load_latest() -> Dict[str, Any]:
    if LATEST.exists():
        try:
            return json.loads(LATEST.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {
        "fetched_at": None,
        "signals": {},
        "compact": "(no market signals cached yet)",
        "ok": False,
    }


def load_for_bucket(day: str, slot: str) -> Dict[str, Any]:
    p = hourly_dir(day, slot) / "signals.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return load_latest()


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Fetch VIX / bonds / oil signals for packs")
    p.add_argument("--bucket", help="Optional YYYY-MM-DDTHH:MM to also write hourly signals.json")
    p.add_argument("--print-compact", action="store_true")
    args = p.parse_args(argv)

    payload = fetch_signals(bucket=args.bucket)
    wrote = write_signals(payload, bucket=args.bucket)
    out = {
        "wrote": wrote,
        "fetched_at": payload.get("fetched_at"),
        "ok_count": sum(1 for s in (payload.get("signals") or {}).values() if s.get("ok")),
        "errors": payload.get("errors") or {},
    }
    if args.print_compact:
        out["compact"] = payload.get("compact")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
