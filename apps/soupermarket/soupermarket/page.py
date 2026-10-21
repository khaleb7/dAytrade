"""Day recap page. Numbers only; no order controls."""

from __future__ import annotations

from html import escape
from typing import Any


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _signed(value: float) -> str:
    return f"{'+' if value > 0 else '-'}${abs(value):,.2f}"


def _pct(value: float) -> str:
    return f"{value:+.2f}%"


def _qty(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _chart(dates: list[str], series: list[tuple[str, str, list[float]]]) -> str:
    if len(dates) < 2 or not series:
        return ""
    width, height = 720, 280
    left, right, top, bottom = 56, 16, 32, 36
    plot_w = width - left - right
    plot_h = height - top - bottom
    values = [v for _, _, data in series for v in data]
    low = min(values)
    high = max(values)
    if high <= low:
        high = low + 1
    pad = (high - low) * 0.08
    low -= pad
    high += pad

    def x_at(i: int) -> float:
        return left + plot_w * i / (len(dates) - 1)

    def y_at(v: float) -> float:
        return top + plot_h * (1 - (v - low) / (high - low))

    lines = []
    for name, color, data in series:
        pts = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(data))
        lines.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{pts}" />')
        lines.append(
            f'<circle cx="{x_at(len(data) - 1):.1f}" cy="{y_at(data[-1]):.1f}" r="3" fill="{color}" />'
        )
    labels = []
    for frac, idx in ((0, 0), (0.5, len(dates) // 2), (1, len(dates) - 1)):
        labels.append(
            f'<text x="{x_at(idx):.1f}" y="{height - 10}" text-anchor="{"start" if frac == 0 else "end" if frac == 1 else "middle"}" '
            f'fill="#5c564e" font-size="12">{escape(dates[idx][5:])}</text>'
        )
    for tick, anchor in ((high, "start"), ((high + low) / 2, "middle"), (low, "end")):
        y = y_at(tick)
        labels.append(
            f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" fill="#5c564e" font-size="12">{tick:,.0f}</text>'
        )
        labels.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#e4e0d8" />')
    legend = []
    for i, (name, color, _) in enumerate(series):
        x = left + i * 110
        legend.append(
            f'<rect x="{x}" y="4" width="10" height="10" fill="{color}" />'
            f'<text x="{x + 16}" y="13" fill="#1c1916" font-size="12">{escape(name)}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height + 8}" role="img" aria-label="Account versus SPY, QQQ, and DIA">'
        + "".join(labels)
        + "".join(lines)
        + "".join(legend)
        + "</svg>"
    )


def render(view: dict[str, Any]) -> str:
    day = escape(str(view["day_label"]))
    equity = _money(view["equity"])
    change = view["day_change"]
    change_pct = view["day_change_pct"]
    change_html = f"{_signed(change)} ({_pct(change_pct)})" if view["last_equity"] > 0 else "—"
    cash = _money(view["cash"])
    trades = view["trades"]
    if trades:
        body = []
        for trade in trades:
            side = escape(trade["side"])
            body.append(
                "<tr>"
                f"<td>{escape(trade['time'])}</td>"
                f"<td>{escape(trade['symbol'])}</td>"
                f"<td class=\"{side}\">{side}</td>"
                f"<td class=\"num\">{_qty(trade['qty'])}</td>"
                f"<td class=\"num\">{_money(trade['price'])}</td>"
                f"<td class=\"num\">{_money(trade['notional'])}</td>"
                "</tr>"
            )
        trade_table = (
            "<table><thead><tr><th>Time ET</th><th>Symbol</th><th>Side</th>"
            "<th>Qty</th><th>Price</th><th>Notional</th></tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table>"
        )
    else:
        trade_table = '<p class="empty">No fills this session.</p>'

    positions = view["positions"]
    if positions:
        pos_bits = [
            f"{escape(p['symbol'])} {_qty(p['qty'])} @ {_money(p['price'])}"
            for p in positions
        ]
        held = ", ".join(pos_bits)
    else:
        held = "flat"

    end_rows = []
    for name, color, value, pct in view["ending"]:
        end_rows.append(
            "<tr>"
            f"<td><span class=\"swatch\" style=\"background:{color}\"></span>{escape(name)}</td>"
            f"<td class=\"num\">{_money(value)}</td>"
            f"<td class=\"num\">{_pct(pct)}</td>"
            "</tr>"
        )
    chart = _chart(
        view["dates"],
        [(name, color, view["series"][name]) for name, color, _, _ in view["ending"]],
    )
    start = escape(view["start"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Day recap {day}</title>
  <style>
    :root {{ color-scheme: light; --ink: #1c1916; --muted: #5c564e; --line: #e4e0d8; --paper: #faf8f5; --buy: #1f6b45; --sell: #8a3b2e; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font: 16px/1.45 Georgia, "Iowan Old Style", serif; color: var(--ink); background: var(--paper); }}
    main {{ max-width: 880px; margin: 0 auto; padding: 28px 20px 48px; }}
    h1 {{ font-size: 28px; font-weight: 600; margin: 0 0 4px; }}
    h2 {{ font-size: 18px; font-weight: 600; margin: 28px 0 8px; }}
    p {{ margin: 0 0 8px; }}
    .muted {{ color: var(--muted); font-size: 14px; }}
    .stats {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }}
    .stat {{ border-top: 1px solid var(--line); padding-top: 8px; }}
    .stat b {{ display: block; font-size: 22px; font-variant-numeric: tabular-nums; }}
    table {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }}
    th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); font-size: 15px; }}
    th {{ color: var(--muted); font-weight: 600; font-size: 13px; }}
    .num {{ text-align: right; }}
    .buy {{ color: var(--buy); }}
    .sell {{ color: var(--sell); }}
    .empty {{ color: var(--muted); }}
    svg {{ width: 100%; height: auto; display: block; margin-top: 8px; }}
    .swatch {{ display: inline-block; width: 10px; height: 10px; margin-right: 8px; }}
    @media (max-width: 640px) {{
      .stats {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 24px; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>{day}</h1>
    <p class="muted">Read-only recap. This page does not place orders.</p>
    <section class="stats">
      <div class="stat"><span class="muted">Equity</span><b>{equity}</b></div>
      <div class="stat"><span class="muted">Day change</span><b>{change_html}</b></div>
      <div class="stat"><span class="muted">Cash</span><b>{cash}</b></div>
    </section>
    <h2>Trades</h2>
    {trade_table}
    <p class="muted">Held now: {held}</p>
    <h2>$1,000 at the first mark, {start}</h2>
    {chart}
    <table>
      <thead><tr><th></th><th class="num">Now</th><th class="num">Since start</th></tr></thead>
      <tbody>{"".join(end_rows)}</tbody>
    </table>
    <p class="muted">Account equity from Alpaca. SPY, QQQ, and DIA are IEX daily closes, rebased to $1,000 on the same first day. {escape(view["status"])}</p>
  </main>
</body>
</html>
"""


def render_error(message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Day recap</title></head>
<body style="font: 16px/1.45 Georgia, serif; margin: 32px;">
<p>{escape(message)}</p>
<p>The account was not read. No order was sent.</p>
</body></html>"""
