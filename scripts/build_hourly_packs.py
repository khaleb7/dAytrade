"""Build per-agent RTH markdown packs from news + book + lessons + day-end analysis."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from hour_bucket import as_of_iso, cutoff_utc, normalize_slot, parse_hour_bucket, slot_key
from paths import (
    BOOK_PORTFOLIO,
    LESSONS,
    PROMPTS,
    active_agent_ids,
    day_end_analysis_path,
    hourly_dir,
    hourly_news_path,
    hourly_pack_path,
    hourly_signals_path,
)
from trading_calendar import parse_day, prev_trading_day


def load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def lessons_excerpt(path: Path = LESSONS, n: int = 20) -> str:
    if not path.exists():
        return "(no lessons yet)"
    lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
    return "\n".join(lines[-n:]) if lines else "(no lessons yet)"


def day_end_excerpt(before_day: str) -> str:
    d = parse_day(before_day)
    for _ in range(10):
        d = prev_trading_day(d)
        p = day_end_analysis_path(d.isoformat())
        if not p.exists():
            continue
        try:
            data = load_json(p)
            brief = data.get("for_next_session") or json.dumps(data, indent=2)
            return str(brief)[:4000]
        except Exception:  # noqa: BLE001
            continue
    return "(no prior day-end analysis yet)"


def market_signals_block(day: str, slot: str) -> tuple[str, str]:
    """Return (compact_text, vix_line)."""
    from paths import SIGNALS_LATEST

    for p in (hourly_signals_path(day, slot), SIGNALS_LATEST):
        if not p.exists():
            continue
        try:
            data = load_json(p)
            compact = data.get("compact") or "(market signals present but compact text missing)"
            vix = (data.get("signals") or {}).get("vix") or {}
            if vix.get("ok") and vix.get("level") is not None:
                ch = vix.get("change")
                pct = vix.get("change_pct")
                bits = []
                if ch is not None:
                    bits.append(f"{ch:+.2f}")
                if pct is not None:
                    bits.append(f"{pct:+.2f}%")
                delta = (" Δ " + " / ".join(bits)) if bits else ""
                vix_line = f"VIX: {float(vix['level']):.2f}{delta} as_of={vix.get('as_of') or '?'}"
            else:
                vix_line = "VIX: unavailable"
            return str(compact), vix_line
        except Exception:  # noqa: BLE001
            continue
    return (
        "(no market signals cached yet — treat as unknown; do not invent levels)",
        "VIX: unavailable",
    )


def render_pack(
    *,
    agent_id: str,
    as_of: str,
    cutoff: str,
    news: Dict[str, Any],
    book: Dict[str, Any],
    lessons: str,
    day_end: str,
    market_signals: str,
    vix: str,
    template: str,
) -> str:
    return (
        template.replace("{{AS_OF}}", as_of)
        .replace("{{AGENT_ID}}", agent_id)
        .replace("{{CUTOFF_UTC}}", cutoff)
        .replace("{{NEWS_JSON}}", json.dumps(news, indent=2))
        .replace("{{BOOK_JSON}}", json.dumps(book, indent=2))
        .replace("{{LESSONS_EXCERPT}}", lessons)
        .replace("{{DAY_END_ANALYSIS}}", day_end)
        .replace("{{MARKET_SIGNALS}}", market_signals)
        .replace("{{VIX}}", vix)
    )


def build_hourly_packs(
    day: str,
    hour_or_slot: int | str,
    *,
    minute: int = 0,
    news_path: Optional[Path] = None,
    book_path: Path = BOOK_PORTFOLIO,
    template_path: Optional[Path] = None,
) -> List[Path]:
    from datetime import date as date_cls

    d = date_cls.fromisoformat(day)
    slot = normalize_slot(hour_or_slot, minute)
    hour = int(slot[:2])
    minute = int(slot[2:])
    as_of = as_of_iso(d, hour, minute)
    cutoff = cutoff_utc(d, hour, minute).isoformat().replace("+00:00", "Z")

    npath = news_path or hourly_news_path(day, slot)
    if npath.exists():
        news = load_json(npath)
    else:
        news = {"as_of": as_of, "items": [], "mode": "missing"}

    book = load_json(book_path) if book_path.exists() else {"cash_usd": 1000.0, "positions": [], "equity_usd": 1000.0}
    from alpaca_client import sizing_book

    book = sizing_book(book)
    lessons = lessons_excerpt()
    day_end = day_end_excerpt(day)
    market_signals, vix = market_signals_block(day, slot)
    tmpl = (template_path or (PROMPTS / "hourly_input_template.md")).read_text()

    written: List[Path] = []
    for aid in active_agent_ids():
        text = render_pack(
            agent_id=aid,
            as_of=as_of,
            cutoff=cutoff,
            news=news,
            book=book,
            lessons=lessons,
            day_end=day_end,
            market_signals=market_signals,
            vix=vix,
            template=tmpl,
        )
        out = hourly_pack_path(day, slot, aid)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        written.append(out)
    return written


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Build A1 RTH prompt pack (single-agent)")
    p.add_argument("--bucket", required=True, help="YYYY-MM-DDTHH:MM")
    p.add_argument("--news", type=Path)
    p.add_argument("--book", type=Path, default=BOOK_PORTFOLIO)
    p.add_argument("--utc", action="store_true")
    args = p.parse_args(argv)

    day_d, hour, minute, slot, _ = parse_hour_bucket(args.bucket, utc=args.utc)
    paths = build_hourly_packs(
        day_d.isoformat(), slot, news_path=args.news, book_path=args.book
    )
    print(
        json.dumps(
            {"wrote": [str(x) for x in paths], "dir": str(hourly_dir(day_d.isoformat(), slot))},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
