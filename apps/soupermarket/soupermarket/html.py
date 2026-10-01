"""Broadsheet HTML. One page is a whole issue."""

from __future__ import annotations

from datetime import date
from html import escape
from typing import Any


def long_date(iso_day: str) -> str:
    d = date.fromisoformat(iso_day)
    return f"{d.strftime('%A, %B')} {d.day}, {d.year}"


def _href(url: str) -> str:
    if url.startswith("https://") or url.startswith("http://"):
        return url
    return ""


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --ink: #1c140c;
      --rule: #1c140c;
      --paper: #f3ead7;
      --muted: #5c5146;
      --boomer: #1e3a5f;
      --genx: #6e2b3c;
      --mill: #1f6f62;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #d9d0c1;
      color: var(--ink);
      font-family: Georgia, "Palatino Linotype", Palatino, serif;
    }}
    .sheet {{
      max-width: 1040px;
      margin: 0 auto;
      background: var(--paper);
      padding: 28px 32px 64px;
      min-height: 100vh;
    }}
    .masthead {{
      text-align: center;
      border-top: 3px solid var(--rule);
      border-bottom: 3px solid var(--rule);
      padding: 14px 0 10px;
    }}
    .masthead a {{ color: inherit; text-decoration: none; }}
    .masthead h1 {{
      font-size: clamp(40px, 7vw, 72px);
      line-height: 0.9;
      letter-spacing: -0.03em;
      margin: 0;
      font-weight: 700;
    }}
    .tagline {{
      margin: 8px 0 0;
      font-variant: small-caps;
      letter-spacing: 0.18em;
      font-size: 13px;
    }}
    .meta {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      border-bottom: 1px solid var(--rule);
      padding: 8px 0;
      font-size: 14px;
    }}
    .archive {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 14px;
      padding: 10px 0 4px;
      font-size: 14px;
    }}
    .archive a {{ color: var(--ink); }}
    .archive a.current {{ font-weight: 700; text-decoration: none; }}
    h2 {{
      font-size: 28px;
      line-height: 1.15;
      margin: 18px 0 8px;
    }}
    .deck {{ color: var(--muted); margin: 0 0 18px; }}
    .front {{ list-style: none; padding: 0; margin: 0; }}
    .front li {{
      padding: 10px 0;
      border-top: 1px solid rgba(28, 20, 12, 0.25);
    }}
    .kicker {{
      font-variant: small-caps;
      letter-spacing: 0.08em;
      font-size: 12px;
      color: var(--muted);
    }}
    .front a.title {{ color: inherit; }}
    .summary {{ margin: 4px 0 0; color: var(--muted); font-size: 15px; }}
    .week {{
      margin-top: 28px;
      padding-top: 8px;
      border-top: 3px double var(--rule);
    }}
    .columns {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 22px;
      margin-top: 8px;
    }}
    .col {{ border-top: 4px solid var(--ink); padding-top: 8px; }}
    .col.boomer {{ border-color: var(--boomer); }}
    .col.genx {{ border-color: var(--genx); }}
    .col.millennial {{ border-color: var(--mill); }}
    .col h3 {{ margin: 0 0 8px; font-size: 22px; }}
    .col p {{ margin: 0; line-height: 1.45; font-size: 16px; }}
    .pager {{
      display: flex;
      justify-content: space-between;
      margin-top: 28px;
      border-top: 1px solid var(--rule);
      padding-top: 12px;
    }}
    .pager a {{ color: var(--ink); }}
    .empty {{ padding: 24px 0; }}
    @media (max-width: 800px) {{
      .sheet {{ padding: 18px 16px 48px; }}
      .columns {{ grid-template-columns: 1fr; }}
      .meta {{ flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <main class="sheet">
    {body}
  </main>
</body>
</html>
"""


def _archive(dates: list[str], current: str | None) -> str:
    if not dates:
        return ""
    links = []
    for edition in dates:
        label = escape(long_date(edition))
        if edition == current:
            links.append(f'<a class="current" href="/issues/{edition}">{label}</a>')
        else:
            links.append(f'<a href="/issues/{edition}">{label}</a>')
    return '<nav class="archive" aria-label="Earlier issues">' + " · ".join(links) + "</nav>"


def _masthead() -> str:
    return """
<header class="masthead">
  <h1><a href="/">Souper Intelligence</a></h1>
  <p class="tagline">A daily reading of the wire</p>
</header>
"""


def render_issue(issue: dict[str, Any], dates: list[str]) -> str:
    edition = str(issue["edition_date"])
    idx = dates.index(edition) if edition in dates else -1
    newer = dates[idx - 1] if idx > 0 else ""
    older = dates[idx + 1] if idx >= 0 and idx + 1 < len(dates) else ""
    front_items = []
    for item in issue.get("front") or []:
        title = escape(str(item.get("title") or ""))
        href = _href(str(item.get("url") or ""))
        title_html = f'<a class="title" href="{escape(href)}">{title}</a>' if href else title
        summary = str(item.get("summary") or "").strip()
        summary_html = f'<p class="summary">{escape(summary)}</p>' if summary else ""
        front_items.append(
            "<li>"
            f'<div class="kicker">{escape(str(item.get("source_label") or ""))}</div>'
            f"<div>{title_html}</div>"
            f"{summary_html}"
            "</li>"
        )
    if not front_items:
        front_items.append("<li>No items were filed before this edition's cutoff.</li>")
    columns = []
    for col in issue.get("commentaries") or []:
        cid = escape(str(col.get("id") or "col"))
        columns.append(
            f'<section class="col {cid}">'
            f'<h3>{escape(str(col.get("name") or ""))}</h3>'
            f'<p>{escape(str(col.get("body") or ""))}</p>'
            "</section>"
        )
    week = issue.get("week") or {}
    pager = ['<nav class="pager">']
    pager.append(
        f'<a href="/issues/{older}">Earlier issue</a>' if older else "<span></span>"
    )
    pager.append(
        f'<a href="/issues/{newer}">Later issue</a>' if newer else "<span></span>"
    )
    pager.append("</nav>")
    number = issue.get("issue_number") or ""
    body = (
        _masthead()
        + f'<div class="meta"><span>{escape(long_date(edition))}</span>'
        + f"<span>No. {escape(str(number))}</span></div>"
        + _archive(dates, edition)
        + f'<h2>{escape(str(issue.get("kicker") or ""))}</h2>'
        + '<ol class="front">'
        + "".join(front_items)
        + "</ol>"
        + '<section class="week"><h2>The week in the wire</h2>'
        + f'<p class="deck">{escape(str(week.get("blurb") or ""))}</p></section>'
        + '<h2>Three commentaries</h2>'
        + '<div class="columns">'
        + "".join(columns)
        + "</div>"
        + "".join(pager)
    )
    return _page(f"Souper Intelligence — {long_date(edition)}", body)


def render_waiting(publish_hour: int) -> str:
    body = (
        _masthead()
        + '<section class="empty">'
        + "<h2>The presses have not run yet.</h2>"
        + f"<p>The first edition is filed after {publish_hour}:00 Eastern, once the day's wire is in.</p>"
        + "</section>"
    )
    return _page("Souper Intelligence", body)
