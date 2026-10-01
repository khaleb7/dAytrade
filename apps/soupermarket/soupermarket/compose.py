"""Build one edition from wire copy. Commentaries quote headlines; they do not invent them."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

SOURCE_LABELS = {
    "reuters": "Reuters",
    "yahoo_finance": "Yahoo Finance",
    "marketwatch": "MarketWatch",
    "sec_edgar": "SEC EDGAR",
}

_TOKEN = re.compile(r"\b[A-Z]{1,5}\b")
_STOP = {
    "A",
    "I",
    "AI",
    "ALL",
    "AM",
    "AN",
    "AND",
    "ARE",
    "AS",
    "AT",
    "BE",
    "BIG",
    "BUT",
    "BY",
    "CAN",
    "CEO",
    "CO",
    "CORP",
    "CPI",
    "DAY",
    "DOW",
    "ETF",
    "ETFS",
    "FDA",
    "FED",
    "FOR",
    "FROM",
    "GDP",
    "HAS",
    "HAVE",
    "HOW",
    "IN",
    "INC",
    "IPO",
    "IS",
    "IT",
    "ITS",
    "LLC",
    "LTD",
    "MAY",
    "NEW",
    "NOT",
    "NOW",
    "NYSE",
    "OF",
    "ON",
    "OR",
    "PM",
    "Q1",
    "Q2",
    "Q3",
    "Q4",
    "SAYS",
    "SEC",
    "THE",
    "THIS",
    "TO",
    "TOP",
    "UK",
    "US",
    "USA",
    "WAS",
    "WEEK",
    "WHAT",
    "WHO",
    "WHY",
    "WILL",
    "WITH",
    "YEAR",
    "YOUR",
}


def _label(source: str) -> str:
    return SOURCE_LABELS.get(source, source.replace("_", " ").title())


def _front(articles: list[dict[str, Any]], day_start: str, as_of: str) -> list[dict[str, Any]]:
    rows = [
        a
        for a in articles
        if a.get("published") and day_start <= str(a["published"]) < as_of and a.get("title")
    ]
    rows.sort(key=lambda a: str(a["published"]), reverse=True)
    return rows[:24]


def _top_names(articles: list[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    for article in articles:
        seen = set(_TOKEN.findall(str(article.get("title") or "")))
        for token in seen:
            if token in _STOP or token.isdigit():
                continue
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [name for name, n in ranked if n >= 2][:6]


def _week_blurb(articles: list[dict[str, Any]], names: list[str], start: date, end: date) -> str:
    if not articles:
        return (
            f"From {start.isoformat()} through {end.isoformat()} the tracked wire had nothing filed before this edition's cutoff."
        )
    counts: dict[str, int] = {}
    for article in articles:
        source = str(article.get("source") or "other")
        counts[source] = counts.get(source, 0) + 1
    bits = [f"{_label(source)} {n}" for source, n in sorted(counts.items())]
    noun = "item" if len(articles) == 1 else "items"
    line = (
        f"From {start.isoformat()} through {end.isoformat()} the wire carried {len(articles)} {noun} "
        f"({', '.join(bits)})."
    )
    if names:
        line += " Repeated names: " + ", ".join(names) + "."
    else:
        line += " No name showed up often enough to call a theme."
    return line


def compose(
    *,
    edition: date,
    as_of: datetime,
    day_start: datetime,
    articles: list[dict[str, Any]],
    commentaries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    as_of_s = _iso(as_of)
    start_s = _iso(day_start)
    week_start = date.fromordinal(edition.toordinal() - 6)
    front = _front(articles, start_s, as_of_s)
    names = _top_names(articles)
    lead = front[0]["title"] if front else "The wire was quiet"
    return {
        "edition_date": edition.isoformat(),
        "as_of": as_of_s,
        "masthead": "Souper Intelligence",
        "kicker": lead,
        "front": [
            {
                "source": a.get("source") or "",
                "source_label": _label(str(a.get("source") or "")),
                "title": a.get("title") or "",
                "url": a.get("url") or "",
                "published": a.get("published") or "",
                "summary": (a.get("summary") or "")[:400],
            }
            for a in front
        ],
        "week": {
            "start": week_start.isoformat(),
            "end": edition.isoformat(),
            "item_count": len(articles),
            "top_names": names,
            "blurb": _week_blurb(articles, names, week_start, edition),
        },
        "commentaries": list(commentaries or []),
    }


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
