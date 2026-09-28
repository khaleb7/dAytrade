"""Fetch daily OHLCV via yfinance and freeze under state/market/YYYY-MM-DD.json."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from paths import MARKET, market_path
from trading_calendar import is_trading_day, parse_day

# Default liquid universe for pack building / smoke fills.
DEFAULT_SYMBOLS = [
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "VTI",
    "BND",
    "GLD",
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
    "JPM",
    "XOM",
    "UNH",
    "JNJ",
    "XLF",
    "XLK",
]


def fetch_bars_yfinance(symbols: List[str], day: str) -> Dict[str, Dict[str, float]]:
    import yfinance as yf

    d = parse_day(day)
    start = d.isoformat()
    end = (d + timedelta(days=1)).isoformat()
    bars: Dict[str, Dict[str, float]] = {}

    # Batch download is more reliable for many tickers.
    data = yf.download(
        tickers=" ".join(symbols),
        start=start,
        end=end,
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )
    if data is None or data.empty:
        # fallback per-symbol
        for sym in symbols:
            t = yf.Ticker(sym)
            hist = t.history(start=start, end=end, auto_adjust=True)
            if hist is None or hist.empty:
                continue
            row = hist.iloc[0]
            bars[sym] = {
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
            }
        return bars

    # MultiIndex columns when multiple tickers
    if getattr(data.columns, "nlevels", 1) > 1:
        for sym in symbols:
            try:
                sub = data[sym]
            except KeyError:
                continue
            if sub is None or sub.empty:
                continue
            row = sub.dropna(how="all")
            if row.empty:
                continue
            r = row.iloc[0]
            if any(k not in r or (r[k] != r[k]) for k in ("Open", "Close")):
                continue
            bars[sym] = {
                "open": float(r["Open"]),
                "high": float(r["High"]),
                "low": float(r["Low"]),
                "close": float(r["Close"]),
                "volume": float(r.get("Volume", 0) or 0),
            }
    else:
        # single ticker
        sym = symbols[0]
        row = data.dropna(how="all")
        if not row.empty:
            r = row.iloc[0]
            bars[sym] = {
                "open": float(r["Open"]),
                "high": float(r["High"]),
                "low": float(r["Low"]),
                "close": float(r["Close"]),
                "volume": float(r.get("Volume", 0) or 0),
            }
    return bars


def write_market(
    day: str,
    bars: Dict[str, Dict[str, float]],
    source: str = "yfinance",
    out_dir: Optional[Path] = None,
) -> Path:
    out = (out_dir or MARKET) / f"{day}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": day,
        "source": source,
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "bars": bars,
    }
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return out


def load_market(day: str, path: Optional[Path] = None) -> Dict:
    p = path or market_path(day)
    with p.open() as f:
        return json.load(f)


def opens_from_market(market: Dict) -> Dict[str, float]:
    return {s: float(b["open"]) for s, b in market.get("bars", {}).items()}


def closes_from_market(market: Dict) -> Dict[str, float]:
    return {s: float(b["close"]) for s, b in market.get("bars", {}).items()}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Fetch OHLCV for a trading day via yfinance")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    p.add_argument("--out-dir", type=Path, default=MARKET)
    p.add_argument("--from-fixture", type=Path, help="Copy/write from fixture JSON instead of network")
    p.add_argument("--allow-non-trading-day", action="store_true")
    args = p.parse_args(argv)

    d = parse_day(args.date)
    if not args.allow_non_trading_day and not is_trading_day(d):
        print(f"error: {args.date} is not an NYSE trading day", file=sys.stderr)
        return 1

    if args.from_fixture:
        data = json.loads(args.from_fixture.read_text())
        bars = data.get("bars", data)
        path = write_market(args.date, bars, source=data.get("source", "fixture"), out_dir=args.out_dir)
    else:
        try:
            bars = fetch_bars_yfinance(list(args.symbols), args.date)
        except Exception as e:
            print(f"error fetching market: {e}", file=sys.stderr)
            return 1
        if not bars:
            print("error: no bars returned", file=sys.stderr)
            return 1
        path = write_market(args.date, bars, out_dir=args.out_dir)

    print(json.dumps({"wrote": str(path), "symbols": sorted(json.loads(path.read_text())["bars"].keys())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
