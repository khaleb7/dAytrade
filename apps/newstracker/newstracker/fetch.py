"""One-source fetches. A 429 records eligibility later; it does not retry in a loop."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .config import USER_AGENT, Config


@dataclass
class FetchResult:
    articles: list[dict[str, Any]]
    bars: list[dict[str, Any]]
    etag: str | None
    error: str | None
    retry_after_s: float | None
    not_modified: bool = False


def _parse_ts(text: str | None) -> datetime | None:
    if not text:
        return None
    raw = text.strip()
    try:
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        if "T" in raw:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _strip_tags(text: str) -> str:
    out: list[str] = []
    skip = False
    for ch in text:
        if ch == "<":
            skip = True
            continue
        if ch == ">":
            skip = False
            continue
        if not skip:
            out.append(ch)
    return " ".join("".join(out).split())


def parse_feed(xml_bytes: bytes, source: str) -> list[dict[str, Any]]:
    """Parse RSS 2.0 items and Atom entries."""
    items: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = _parse_ts(item.findtext("pubDate"))
        desc = _strip_tags(item.findtext("description") or "")
        if not title:
            continue
        items.append(
            {
                "source": source,
                "title": title,
                "url": link,
                "published": _iso(pub),
                "summary": desc[:500],
            }
        )
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//a:entry", ns):
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        link_el = entry.find("a:link", ns)
        link = link_el.get("href", "") if link_el is not None else ""
        pub = _parse_ts(
            entry.findtext("a:updated", default="", namespaces=ns)
            or entry.findtext("a:published", default="", namespaces=ns)
        )
        summary = _strip_tags(entry.findtext("a:summary", default="", namespaces=ns) or "")
        if not title:
            continue
        items.append(
            {
                "source": source,
                "title": title,
                "url": link,
                "published": _iso(pub),
                "summary": summary[:500],
            }
        )
    return items


def _retry_after(header: str | None) -> float | None:
    if not header:
        return None
    header = header.strip()
    try:
        return float(header)
    except ValueError:
        return None


def http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> tuple[int, bytes, dict[str, str]]:
    req_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        req_headers.update(headers)
    req = Request(url, headers=req_headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, body, hdrs
    except HTTPError as e:
        body = e.read() if e.fp is not None else b""
        hdrs = {k.lower(): v for k, v in e.headers.items()} if e.headers else {}
        return e.code, body, hdrs


def _rate_limited(status: int, body: bytes) -> bool:
    if status == 429:
        return True
    sample = body[:500].decode("utf-8", errors="replace").lower()
    return "rate limit" in sample or "too many requests" in sample


def fetch_feed(url: str, source: str, etag: str | None) -> FetchResult:
    headers: dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
    try:
        status, body, hdrs = http_get(url, headers=headers)
    except (URLError, TimeoutError, OSError) as e:
        return FetchResult([], [], None, str(e), None)
    if status == 304:
        return FetchResult([], [], etag, None, None, not_modified=True)
    if _rate_limited(status, body):
        return FetchResult([], [], None, f"HTTP {status}", _retry_after(hdrs.get("retry-after")))
    if status >= 400:
        return FetchResult([], [], None, f"HTTP {status}", None)
    return FetchResult(parse_feed(body, source), [], hdrs.get("etag"), None, None)


def fetch_bars(cfg: Config, symbol: str) -> FetchResult:
    if not cfg.alpaca_configured:
        return FetchResult([], [], None, "alpaca keys unset", None)
    query = urlencode(
        {
            "timeframe": "1Min",
            "limit": "5",
            "feed": cfg.alpaca_feed,
        }
    )
    url = f"{cfg.alpaca_data_url}/v2/stocks/{quote(symbol)}/bars?{query}"
    headers = {
        "APCA-API-KEY-ID": cfg.alpaca_key,
        "APCA-API-SECRET-KEY": cfg.alpaca_secret,
        "Accept": "application/json",
    }
    try:
        status, body, hdrs = http_get(url, headers=headers, timeout=20)
    except (URLError, TimeoutError, OSError) as e:
        return FetchResult([], [], None, str(e), None)
    if _rate_limited(status, body):
        return FetchResult([], [], None, f"HTTP {status}", _retry_after(hdrs.get("retry-after")))
    if status >= 400:
        return FetchResult([], [], None, f"HTTP {status}", None)
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return FetchResult([], [], None, "invalid json", None)
    raw_bars = payload.get("bars") or []
    bars: list[dict[str, Any]] = []
    for bar in raw_bars:
        ts = bar.get("t")
        if not ts:
            continue
        bars.append(
            {
                "symbol": symbol,
                "ts": str(ts).replace("+00:00", "Z"),
                "open": bar.get("o"),
                "high": bar.get("h"),
                "low": bar.get("l"),
                "close": bar.get("c"),
                "volume": bar.get("v"),
            }
        )
    return FetchResult([], bars, None, None, None)
