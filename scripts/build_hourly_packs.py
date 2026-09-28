"""Build per-agent hourly markdown packs from news + book + lessons."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from hour_bucket import as_of_iso, cutoff_utc, parse_hour_bucket
from paths import (
    BOOK_PORTFOLIO,
    LESSONS,
    PROMPTS,
    hourly_dir,
    hourly_news_path,
    hourly_pack_path,
)

AGENT_IDS = ["A1", "A2", "A3", "A4", "A5"]


def load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def lessons_excerpt(path: Path = LESSONS, n: int = 20) -> str:
    if not path.exists():
        return "(no lessons yet)"
    lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
    return "\n".join(lines[-n:]) if lines else "(no lessons yet)"


def render_pack(
    *,
    agent_id: str,
    as_of: str,
    cutoff: str,
    news: Dict[str, Any],
    book: Dict[str, Any],
    lessons: str,
    template: str,
) -> str:
    return (
        template.replace("{{AS_OF}}", as_of)
        .replace("{{AGENT_ID}}", agent_id)
        .replace("{{CUTOFF_UTC}}", cutoff)
        .replace("{{NEWS_JSON}}", json.dumps(news, indent=2))
        .replace("{{BOOK_JSON}}", json.dumps(book, indent=2))
        .replace("{{LESSONS_EXCERPT}}", lessons)
    )


def build_hourly_packs(
    day: str,
    hour: int,
    *,
    news_path: Optional[Path] = None,
    book_path: Path = BOOK_PORTFOLIO,
    template_path: Optional[Path] = None,
) -> List[Path]:
    from datetime import date as date_cls

    d = date_cls.fromisoformat(day)
    as_of = as_of_iso(d, hour)
    cutoff = cutoff_utc(d, hour).isoformat().replace("+00:00", "Z")

    npath = news_path or hourly_news_path(day, hour)
    if npath.exists():
        news = load_json(npath)
    else:
        news = {"as_of": as_of, "items": [], "mode": "missing"}

    book = load_json(book_path) if book_path.exists() else {"cash_usd": 1000.0, "positions": [], "equity_usd": 1000.0}
    # Agents see the sizing view (~$1000), not raw $100k paper equity
    from alpaca_client import sizing_book

    book = sizing_book(book)
    lessons = lessons_excerpt()
    tmpl = (template_path or (PROMPTS / "hourly_input_template.md")).read_text()

    written: List[Path] = []
    for aid in AGENT_IDS:
        text = render_pack(
            agent_id=aid,
            as_of=as_of,
            cutoff=cutoff,
            news=news,
            book=book,
            lessons=lessons,
            template=tmpl,
        )
        out = hourly_pack_path(day, hour, aid)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        written.append(out)
    return written


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Build A1–A5 hourly prompt packs")
    p.add_argument("--bucket", required=True, help="YYYY-MM-DDTHH")
    p.add_argument("--news", type=Path)
    p.add_argument("--book", type=Path, default=BOOK_PORTFOLIO)
    p.add_argument("--utc", action="store_true")
    args = p.parse_args(argv)

    day_d, hour, _ = parse_hour_bucket(args.bucket, utc=args.utc)
    paths = build_hourly_packs(day_d.isoformat(), hour, news_path=args.news, book_path=args.book)
    print(json.dumps({"wrote": [str(x) for x in paths], "dir": str(hourly_dir(day_d.isoformat(), hour))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
