"""Batch-ingest news into a local cache, then slice day/hour packs (no lookahead).

Commands:
  ingest --backfill-range FROM TO   few large upstream pulls → state/news_cache/
  ingest --live-feeds               RSS/EDGAR once into cache (hourly tick)
  build-day YYYY-MM-DD              cache-only → state/news/YYYY-MM-DD.json
  build-hour YYYY-MM-DDTHH          cache-only → state/hourly/YYYY-MM-DD/HH/news.json
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from hour_bucket import as_of_iso, cutoff_utc, parse_hour_bucket
from paths import NEWS, NEWS_CACHE, hourly_news_path
from trading_calendar import is_trading_day, parse_day, rth_open_utc_iso

USER_AGENT = "DayTradeSimulator/1.0 (+cursor-project; research)"

RSS_SOURCES = {
    "reuters": "https://feeds.reuters.com/reuters/businessNews",
    "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
    "marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories/",
}

EDGAR_ATOM = (
    "https://www.sec.gov/cgi-bin/browse-edgar?"
    "action=getcurrent&type=8-K&company=&dateb=&owner=include&count=40&output=atom"
)

GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_GKG_ZIP = "http://data.gdeltproject.org/gdeltv2/{stamp}.gkg.csv.zip"

# Productive domains first (reuters often empty/paywalled in DOC API).
GDELT_DOMAINS = [
    "finance.yahoo.com",
    "marketwatch.com",
    "sec.gov",
    "reuters.com",
]

DOMAIN_TO_SOURCE = {
    "reuters.com": "reuters",
    "finance.yahoo.com": "yahoo_finance",
    "marketwatch.com": "marketwatch",
    "sec.gov": "sec_edgar",
}

# URL substrings → source tag (order matters; first match wins)
URL_SOURCE_RULES = [
    ("finance.yahoo.com", "yahoo_finance"),
    ("marketwatch.com", "marketwatch"),
    ("sec.gov", "sec_edgar"),
    ("www.reuters.com", "reuters"),
    ("reuters.com/", "reuters"),
]

# Cache layout under state/news_cache/
ITEMS_JSONL = "items.jsonl"
GAPS_JSONL = "gaps.jsonl"
INGEST_LOG = "ingest_log.jsonl"
MANIFEST = "manifest.json"

# Polite GDELT DOC pacing (seconds between requests). Stay well under 429.
GDELT_SLEEP = 6.0
GDELT_MAX_RECORDS = 250
# Fortnight chunks → fewer requests than per-day × per-domain
GDELT_CHUNK_DAYS = 14
GDELT_429_RETRIES = 1  # one backoff then record gap — do not spin
GDELT_429_BASE_SLEEP = 20.0

# GKG dump sampling: UTC hours per calendar day (CDN, not DOC API — avoids 429)
GKG_HOURS_UTC = (0, 8, 12)
GKG_SLEEP = 0.35
_PAGE_TITLE_RE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.I | re.S)

# US House STOCK Act PTR index (official clerk bulk zip)
HOUSE_FD_ZIP = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
HOUSE_PTR_PDF = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"
# FilingType P = Periodic Transaction Report (actual trade disclosures)
HOUSE_PTR_FILING_TYPE = "P"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _http_get(url: str, timeout: int = 45) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _http_get_backoff(
    url: str,
    *,
    timeout: int = 45,
    max_retries: int = GDELT_429_RETRIES,
    base_sleep: float = GDELT_429_BASE_SLEEP,
) -> Tuple[Optional[bytes], Optional[str]]:
    """GET with limited 429 backoff. Returns (body, error_note). Does not spin forever."""
    last_err: Optional[str] = None
    for attempt in range(max_retries + 1):
        try:
            return _http_get(url, timeout=timeout), None
        except HTTPError as e:
            last_err = f"HTTP {e.code}: {e.reason}"
            if e.code == 429 and attempt < max_retries:
                wait = base_sleep * (2**attempt)
                time.sleep(wait)
                continue
            return None, last_err
        except (URLError, TimeoutError, OSError) as e:
            last_err = str(e)
            if attempt < max_retries:
                time.sleep(base_sleep * (attempt + 1))
                continue
            return None, last_err
    return None, last_err or "unknown error"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_ts(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    text = text.strip()
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        if "T" in text:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    # GDELT seendate YYYYMMDDHHMMSS
    if len(text) >= 14 and text[:14].isdigit():
        try:
            return datetime.strptime(text[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _iso_z(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _cutoff(day: str) -> datetime:
    return datetime.fromisoformat(rth_open_utc_iso(day).replace("Z", "+00:00"))


def _item(
    source: str,
    title: str,
    url: str,
    published: Optional[datetime],
    summary: str = "",
) -> Dict[str, Any]:
    return {
        "source": source,
        "title": (title or "").strip(),
        "url": url or "",
        "published": _iso_z(published),
        "summary": (summary or "").strip()[:500],
    }


def parse_rss(xml_bytes: bytes, source: str, cutoff: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Parse RSS/Atom. If cutoff is set, drop items with published >= cutoff."""
    items: List[Dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = _parse_ts(item.findtext("pubDate"))
        desc = item.findtext("description") or ""
        if not title:
            continue
        if cutoff is not None and pub and pub >= cutoff:
            continue
        items.append(_item(source, title, link, pub, desc))
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//a:entry", ns):
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        link_el = entry.find("a:link", ns)
        link = link_el.get("href", "") if link_el is not None else ""
        pub = _parse_ts(
            entry.findtext("a:updated", default="", namespaces=ns)
            or entry.findtext("a:published", default="", namespaces=ns)
        )
        summary = entry.findtext("a:summary", default="", namespaces=ns) or ""
        if not title:
            continue
        if cutoff is not None and pub and pub >= cutoff:
            continue
        items.append(_item(source, title, link, pub, summary))
    return items


def _parse_gdelt_articles(raw: bytes, source_tag: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return items
    arts = data.get("articles") or data.get("documents") or []
    for a in arts:
        title = a.get("title") or ""
        link = a.get("url") or a.get("sourceurl") or ""
        pub = _parse_ts(a.get("seendate") or a.get("publishedDate") or a.get("date"))
        if not title:
            continue
        items.append(_item(source_tag, title, link, pub, a.get("language", "") or ""))
    return items


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------


def cache_dir(root: Optional[Path] = None) -> Path:
    d = root or NEWS_CACHE
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_paths(root: Optional[Path] = None) -> Dict[str, Path]:
    d = cache_dir(root)
    return {
        "items": d / ITEMS_JSONL,
        "gaps": d / GAPS_JSONL,
        "log": d / INGEST_LOG,
        "manifest": d / MANIFEST,
    }


def _append_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _known_urls(items_path: Path) -> Set[str]:
    urls: Set[str] = set()
    if not items_path.exists():
        return urls
    with items_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            u = row.get("url") or ""
            if u:
                urls.add(u)
    return urls


def _record_gap(
    paths: Dict[str, Path],
    *,
    source: str,
    window_start: str,
    window_end: str,
    reason: str,
    detail: str = "",
) -> None:
    _append_jsonl(
        paths["gaps"],
        [
            {
                "recorded_at": _iso_z(datetime.now(timezone.utc)),
                "source": source,
                "window_start": window_start,
                "window_end": window_end,
                "reason": reason,
                "detail": detail,
            }
        ],
    )


def _write_manifest(paths: Dict[str, Path], extra: Optional[Dict[str, Any]] = None) -> None:
    items = _load_jsonl(paths["items"])
    by_source: Dict[str, int] = {}
    published_dates: List[str] = []
    for it in items:
        by_source[it.get("source", "?")] = by_source.get(it.get("source", "?"), 0) + 1
        if it.get("published"):
            published_dates.append(it["published"][:10])
    manifest = {
        "updated_at": _iso_z(datetime.now(timezone.utc)),
        "item_count": len(items),
        "by_source": by_source,
        "published_min": min(published_dates) if published_dates else None,
        "published_max": max(published_dates) if published_dates else None,
        "layout": {
            "items": ITEMS_JSONL,
            "gaps": GAPS_JSONL,
            "ingest_log": INGEST_LOG,
            "fields": ["source", "title", "url", "published", "summary", "ingested_at", "ingest_id"],
        },
    }
    if extra:
        manifest.update(extra)
    paths["manifest"].write_text(json.dumps(manifest, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Ingest (batch upstream → cache)
# ---------------------------------------------------------------------------


def _daterange_chunks(start: date, end: date, chunk_days: int) -> List[Tuple[date, date]]:
    """Inclusive calendar chunks [chunk_start, chunk_end]."""
    chunks: List[Tuple[date, date]] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def ingest_gdelt_range(
    start: date,
    end: date,
    *,
    cache_root: Optional[Path] = None,
    chunk_days: int = GDELT_CHUNK_DAYS,
    sleep_s: float = GDELT_SLEEP,
    domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Few large GDELT DOC pulls covering [start, end] inclusive calendar days."""
    paths = _cache_paths(cache_root)
    known = _known_urls(paths["items"])
    ingest_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    chunks = _daterange_chunks(start, end, chunk_days)
    added = 0
    requests_ok = 0
    requests_fail = 0
    gaps: List[Dict[str, Any]] = []
    domain_list = domains or GDELT_DOMAINS

    for domain in domain_list:
        source_tag = DOMAIN_TO_SOURCE.get(domain, domain)
        for c_start, c_end in chunks:
            # Full calendar days in UTC for the window
            start_dt = f"{c_start.strftime('%Y%m%d')}000000"
            end_dt = f"{c_end.strftime('%Y%m%d')}235959"
            params = {
                "query": f"domain:{domain}",
                "mode": "ArtList",
                "maxrecords": str(GDELT_MAX_RECORDS),
                "format": "json",
                "startdatetime": start_dt,
                "enddatetime": end_dt,
                "sort": "DateDesc",
            }
            url = f"{GDELT_DOC}?{urlencode(params)}"
            raw, err = _http_get_backoff(url)
            if err or raw is None:
                requests_fail += 1
                gap = {
                    "source": source_tag,
                    "domain": domain,
                    "window_start": c_start.isoformat(),
                    "window_end": c_end.isoformat(),
                    "reason": "http_error",
                    "detail": err or "empty body",
                }
                gaps.append(gap)
                _record_gap(
                    paths,
                    source=source_tag,
                    window_start=c_start.isoformat(),
                    window_end=c_end.isoformat(),
                    reason="http_error",
                    detail=err or "empty body",
                )
                # Extra cool-down after 429, then continue (no spin)
                time.sleep(sleep_s * 2 if err and "429" in err else sleep_s)
                continue

            # Soft rate-limit: GDELT sometimes returns HTML/text instead of JSON
            head = raw[:200].decode("utf-8", errors="replace").lstrip().lower()
            if head.startswith("<!") or "please try again" in head or "rate limit" in head:
                requests_fail += 1
                _record_gap(
                    paths,
                    source=source_tag,
                    window_start=c_start.isoformat(),
                    window_end=c_end.isoformat(),
                    reason="soft_rate_limit",
                    detail=head[:160],
                )
                time.sleep(sleep_s * 2)
                continue

            requests_ok += 1
            arts = _parse_gdelt_articles(raw, source_tag)
            if not arts:
                _record_gap(
                    paths,
                    source=source_tag,
                    window_start=c_start.isoformat(),
                    window_end=c_end.isoformat(),
                    reason="empty_window",
                    detail=f"GDELT returned 0 articles for domain:{domain}",
                )
            rows = []
            now = _iso_z(datetime.now(timezone.utc))
            for art in arts:
                u = art.get("url") or ""
                # Dedup key: url if present else source+title+published
                key = u or f"{art.get('source')}|{art.get('title')}|{art.get('published')}"
                if u and u in known:
                    continue
                if not u and key in known:
                    continue
                known.add(u or key)
                rows.append(
                    {
                        **art,
                        "ingested_at": now,
                        "ingest_id": ingest_id,
                        "ingest_via": "gdelt",
                        "window_start": c_start.isoformat(),
                        "window_end": c_end.isoformat(),
                    }
                )
            added += _append_jsonl(paths["items"], rows)
            if len(arts) >= GDELT_MAX_RECORDS:
                # Cap hit — record possible truncation for this window
                _record_gap(
                    paths,
                    source=source_tag,
                    window_start=c_start.isoformat(),
                    window_end=c_end.isoformat(),
                    reason="maxrecords_cap",
                    detail=f"Hit {GDELT_MAX_RECORDS} cap; window may be truncated",
                )
            time.sleep(sleep_s)

    summary = {
        "ingest_id": ingest_id,
        "via": "gdelt",
        "from": start.isoformat(),
        "to": end.isoformat(),
        "chunk_days": chunk_days,
        "chunks": len(chunks),
        "domains": list(domain_list),
        "requests_ok": requests_ok,
        "requests_fail": requests_fail,
        "items_added": added,
        "gaps_this_run": len(gaps),
    }
    _append_jsonl(paths["log"], [{**summary, "recorded_at": _iso_z(datetime.now(timezone.utc))}])
    _write_manifest(paths, {"last_ingest": summary})
    return summary


def _url_to_source(url: str) -> Optional[str]:
    low = (url or "").lower()
    for needle, tag in URL_SOURCE_RULES:
        if needle in low:
            return tag
    return None


def _parse_gkg_zip(raw: bytes) -> List[Dict[str, Any]]:
    """Extract domain-filtered articles (url + PAGE_TITLE) from one GKG zip."""
    items: List[Dict[str, Any]] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return items
    names = zf.namelist()
    if not names:
        return items
    try:
        text = zf.read(names[0]).decode("utf-8", errors="replace")
    except Exception:
        return items
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        stamp = parts[1].strip() if len(parts) > 1 else ""
        url = parts[4].strip()
        source = _url_to_source(url)
        if not source:
            continue
        extras = parts[-1] if parts else ""
        title = ""
        m = _PAGE_TITLE_RE.search(extras)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
        if not title:
            # Fall back to last path segment — still better than dropping the row
            title = url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")[:120]
        pub = _parse_ts(stamp)
        items.append(_item(source, title, url, pub, ""))
    return items


def ingest_gkg_range(
    start: date,
    end: date,
    *,
    cache_root: Optional[Path] = None,
    hours_utc: Tuple[int, ...] = GKG_HOURS_UTC,
    sleep_s: float = GKG_SLEEP,
) -> Dict[str, Any]:
    """Batch-pull GDELT GKG 15-min dumps (CDN) — avoids DOC API 429s.

    Samples a few UTC hours per calendar day and keeps rows whose URL matches
    Reuters / Yahoo Finance / MarketWatch / SEC.
    """
    paths = _cache_paths(cache_root)
    known = _known_urls(paths["items"])
    ingest_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    added = 0
    files_ok = 0
    files_fail = 0
    files_empty = 0

    cur = start
    while cur <= end:
        for hour in hours_utc:
            # GKG stamps are YYYYMMDDHHMMSS on 15-min boundaries; :00 is always valid
            stamp = f"{cur.strftime('%Y%m%d')}{hour:02d}0000"
            url = GDELT_GKG_ZIP.format(stamp=stamp)
            try:
                raw = _http_get(url, timeout=90)
            except HTTPError as e:
                files_fail += 1
                if e.code != 404:
                    _record_gap(
                        paths,
                        source="gkg",
                        window_start=stamp,
                        window_end=stamp,
                        reason="http_error",
                        detail=f"HTTP {e.code}: {e.reason}",
                    )
                time.sleep(sleep_s)
                continue
            except (URLError, TimeoutError, OSError) as e:
                files_fail += 1
                _record_gap(
                    paths,
                    source="gkg",
                    window_start=stamp,
                    window_end=stamp,
                    reason="http_error",
                    detail=str(e),
                )
                time.sleep(sleep_s)
                continue

            files_ok += 1
            arts = _parse_gkg_zip(raw)
            if not arts:
                files_empty += 1
            now = _iso_z(datetime.now(timezone.utc))
            rows = []
            for art in arts:
                u = art.get("url") or ""
                key = u or f"{art.get('source')}|{art.get('title')}|{art.get('published')}"
                if (u and u in known) or (not u and key in known):
                    continue
                known.add(u or key)
                rows.append(
                    {
                        **art,
                        "ingested_at": now,
                        "ingest_id": ingest_id,
                        "ingest_via": "gkg",
                        "gkg_stamp": stamp,
                    }
                )
            added += _append_jsonl(paths["items"], rows)
            time.sleep(sleep_s)
        cur += timedelta(days=1)

    summary = {
        "ingest_id": ingest_id,
        "via": "gkg",
        "from": start.isoformat(),
        "to": end.isoformat(),
        "hours_utc": list(hours_utc),
        "files_ok": files_ok,
        "files_fail": files_fail,
        "files_empty_match": files_empty,
        "items_added": added,
    }
    _append_jsonl(paths["log"], [{**summary, "recorded_at": _iso_z(datetime.now(timezone.utc))}])
    _write_manifest(paths, {"last_ingest": summary})
    return summary


def _parse_house_filing_date(text: str) -> Optional[datetime]:
    """House FD dates are M/D/YYYY (date-only). Treat as 00:00 America/New_York → UTC."""
    text = (text or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(text, fmt).date()
            break
        except ValueError:
            d = None
    else:
        return None
    # Midnight US Eastern on the filing calendar day (no intraday timestamp published).
    # Same-calendar-day packs may include these before RTH open — acceptable for "color";
    # build-day still enforces published < cutoff_utc.
    try:
        from zoneinfo import ZoneInfo

        et = ZoneInfo("America/New_York")
        return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=et).astimezone(timezone.utc)
    except Exception:
        return datetime(d.year, d.month, d.day, 4, 0, 0, tzinfo=timezone.utc)


def _house_ptr_items_from_zip(raw: bytes, year: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return items
    # Prefer XML; fall back to TSV
    xml_name = next((n for n in zf.namelist() if n.lower().endswith(".xml")), None)
    if xml_name:
        try:
            root = ET.fromstring(zf.read(xml_name))
        except ET.ParseError:
            root = None
        if root is not None:
            for mem in root.findall(".//Member"):
                ftype = (mem.findtext("FilingType") or "").strip()
                if ftype != HOUSE_PTR_FILING_TYPE:
                    continue
                last = (mem.findtext("Last") or "").strip()
                first = (mem.findtext("First") or "").strip()
                prefix = (mem.findtext("Prefix") or "").strip()
                suffix = (mem.findtext("Suffix") or "").strip()
                state = (mem.findtext("StateDst") or "").strip()
                doc_id = (mem.findtext("DocID") or "").strip()
                filing_date = (mem.findtext("FilingDate") or "").strip()
                y = (mem.findtext("Year") or str(year)).strip()
                if not last or not doc_id:
                    continue
                name = " ".join(p for p in (prefix, first, last, suffix) if p).strip()
                pub = _parse_house_filing_date(filing_date)
                url = HOUSE_PTR_PDF.format(year=y, doc_id=doc_id)
                title = f"House PTR: {name} ({state}) filed periodic transaction report"
                summary = (
                    f"STOCK Act Periodic Transaction Report — {name}, {state}, "
                    f"filing date {filing_date}, DocID {doc_id}. Official House Clerk disclosure."
                )
                items.append(_item("politician_trades", title, url, pub, summary))
            return items

    txt_name = next((n for n in zf.namelist() if n.lower().endswith(".txt")), None)
    if not txt_name:
        return items
    text = zf.read(txt_name).decode("utf-8", errors="replace")
    lines = text.strip().splitlines()
    if not lines:
        return items
    header = lines[0].split("\t")
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) < len(header):
            continue
        row = dict(zip(header, cols))
        if (row.get("FilingType") or "").strip() != HOUSE_PTR_FILING_TYPE:
            continue
        last = (row.get("Last") or "").strip()
        first = (row.get("First") or "").strip()
        prefix = (row.get("Prefix") or "").strip()
        suffix = (row.get("Suffix") or "").strip()
        state = (row.get("StateDst") or "").strip()
        doc_id = (row.get("DocID") or "").strip()
        filing_date = (row.get("FilingDate") or "").strip()
        y = (row.get("Year") or str(year)).strip()
        if not last or not doc_id:
            continue
        name = " ".join(p for p in (prefix, first, last, suffix) if p).strip()
        pub = _parse_house_filing_date(filing_date)
        url = HOUSE_PTR_PDF.format(year=y, doc_id=doc_id)
        title = f"House PTR: {name} ({state}) filed periodic transaction report"
        summary = (
            f"STOCK Act Periodic Transaction Report — {name}, {state}, "
            f"filing date {filing_date}, DocID {doc_id}. Official House Clerk disclosure."
        )
        items.append(_item("politician_trades", title, url, pub, summary))
    return items


def ingest_politician_trades(
    *,
    years: Optional[List[int]] = None,
    cache_root: Optional[Path] = None,
    from_day: Optional[date] = None,
    to_day: Optional[date] = None,
) -> Dict[str, Any]:
    """Batch-ingest US House STOCK Act PTR filings from official clerk FD zips.

    One zip per year → filter FilingType=P → append to news cache as source
    `politician_trades` (color / context; not a trade signal).
    """
    paths = _cache_paths(cache_root)
    known = _known_urls(paths["items"])
    ingest_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if years is None:
        y0 = (from_day or date(2026, 6, 1)).year
        y1 = (to_day or datetime.now(timezone.utc).date()).year
        years = list(range(min(y0, y1) - 1, max(y0, y1) + 1))

    added = 0
    years_ok: List[int] = []
    years_fail: List[Dict[str, Any]] = []
    total_ptr = 0

    for year in years:
        url = HOUSE_FD_ZIP.format(year=year)
        raw, err = _http_get_backoff(url, timeout=90, max_retries=2, base_sleep=5.0)
        if err or raw is None:
            years_fail.append({"year": year, "error": err or "empty"})
            _record_gap(
                paths,
                source="politician_trades",
                window_start=f"{year}-01-01",
                window_end=f"{year}-12-31",
                reason="http_error",
                detail=err or "empty House FD zip",
            )
            continue
        years_ok.append(year)
        arts = _house_ptr_items_from_zip(raw, year)
        total_ptr += len(arts)
        now = _iso_z(datetime.now(timezone.utc))
        rows = []
        for art in arts:
            pub = _parse_ts(art.get("published")) if art.get("published") else None
            if from_day and pub and pub.date() < from_day - timedelta(days=7):
                # keep a week of lookback before FROM; drop older
                continue
            if to_day and pub and pub.date() > to_day:
                continue
            u = art.get("url") or ""
            key = u or f"{art.get('source')}|{art.get('title')}|{art.get('published')}"
            if (u and u in known) or (not u and key in known):
                continue
            known.add(u or key)
            rows.append(
                {
                    **art,
                    "ingested_at": now,
                    "ingest_id": ingest_id,
                    "ingest_via": "house_ptr",
                    "chamber": "house",
                }
            )
        added += _append_jsonl(paths["items"], rows)

    summary = {
        "ingest_id": ingest_id,
        "via": "politician_trades",
        "years_ok": years_ok,
        "years_fail": years_fail,
        "ptr_rows_seen": total_ptr,
        "items_added": added,
        "note": "House Clerk STOCK Act PTR index only; Senate eFD not bulk-exported here.",
    }
    _append_jsonl(paths["log"], [{**summary, "recorded_at": _iso_z(datetime.now(timezone.utc))}])
    _write_manifest(paths, {"last_politician_ingest": summary})
    return summary


def ingest_live_feeds(*, cache_root: Optional[Path] = None) -> Dict[str, Any]:
    """One-shot RSS + EDGAR grab into cache (recent headlines only)."""
    paths = _cache_paths(cache_root)
    known = _known_urls(paths["items"])
    ingest_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    added = 0
    errors: List[str] = []

    for name, feed_url in RSS_SOURCES.items():
        raw, err = _http_get_backoff(feed_url, timeout=30, max_retries=2, base_sleep=3.0)
        if err or raw is None:
            errors.append(f"{name}: {err}")
            _record_gap(
                paths,
                source=name,
                window_start="live",
                window_end="live",
                reason="http_error",
                detail=err or "empty",
            )
            continue
        arts = parse_rss(raw, name, cutoff=None)
        now = _iso_z(datetime.now(timezone.utc))
        rows = []
        for art in arts:
            u = art.get("url") or ""
            key = u or f"{art.get('source')}|{art.get('title')}|{art.get('published')}"
            if (u and u in known) or (not u and key in known):
                continue
            known.add(u or key)
            rows.append({**art, "ingested_at": now, "ingest_id": ingest_id, "ingest_via": "rss"})
        added += _append_jsonl(paths["items"], rows)

    raw, err = _http_get_backoff(EDGAR_ATOM, timeout=30, max_retries=2, base_sleep=3.0)
    if err or raw is None:
        errors.append(f"sec_edgar: {err}")
        _record_gap(
            paths,
            source="sec_edgar",
            window_start="live",
            window_end="live",
            reason="http_error",
            detail=err or "empty",
        )
    else:
        arts = parse_rss(raw, "sec_edgar", cutoff=None)
        now = _iso_z(datetime.now(timezone.utc))
        rows = []
        for art in arts:
            u = art.get("url") or ""
            key = u or f"{art.get('source')}|{art.get('title')}|{art.get('published')}"
            if (u and u in known) or (not u and key in known):
                continue
            known.add(u or key)
            rows.append({**art, "ingested_at": now, "ingest_id": ingest_id, "ingest_via": "edgar"})
        added += _append_jsonl(paths["items"], rows)

    summary = {
        "ingest_id": ingest_id,
        "via": "live_feeds",
        "items_added": added,
        "errors": errors,
    }
    _append_jsonl(paths["log"], [{**summary, "recorded_at": _iso_z(datetime.now(timezone.utc))}])
    _write_manifest(paths, {"last_live_ingest": summary})
    return summary


def seed_cache_from_day_packs(
    news_dir: Optional[Path] = None,
    *,
    cache_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Import existing state/news/*.json into cache (no upstream calls)."""
    paths = _cache_paths(cache_root)
    known = _known_urls(paths["items"])
    src = news_dir or NEWS
    ingest_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    added = 0
    files = 0
    if not src.exists():
        return {"items_added": 0, "files": 0}
    now = _iso_z(datetime.now(timezone.utc))
    for path in sorted(src.glob("*.json")):
        files += 1
        try:
            pack = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        rows = []
        for art in pack.get("items") or []:
            if art.get("source") == "fetch_error":
                continue
            u = art.get("url") or ""
            key = u or f"{art.get('source')}|{art.get('title')}|{art.get('published')}"
            if (u and u in known) or (not u and key in known):
                continue
            known.add(u or key)
            rows.append(
                {
                    "source": art.get("source"),
                    "title": art.get("title"),
                    "url": u,
                    "published": art.get("published"),
                    "summary": art.get("summary") or "",
                    "ingested_at": now,
                    "ingest_id": ingest_id,
                    "ingest_via": "seed_day_pack",
                    "seed_from": path.name,
                }
            )
        added += _append_jsonl(paths["items"], rows)
    summary = {"ingest_id": ingest_id, "via": "seed_day_pack", "items_added": added, "files": files}
    _append_jsonl(paths["log"], [{**summary, "recorded_at": now}])
    _write_manifest(paths)
    return summary


# ---------------------------------------------------------------------------
# Day pack builder (cache-only)
# ---------------------------------------------------------------------------


def load_cache_items(cache_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    return _load_jsonl(_cache_paths(cache_root)["items"])


def slice_day_from_cache(
    day: str,
    *,
    cache_root: Optional[Path] = None,
    cache_only: bool = True,
    per_source_cap: int = 40,
) -> Dict[str, Any]:
    """Filter cache items with published strictly before US RTH open on `day`."""
    cutoff = _cutoff(day)
    day_d = parse_day(day)
    # News lookback ~2 calendar days; politician PTRs keep ~14d for color context
    lookback_floor = datetime.combine(day_d - timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc)
    ptr_lookback_floor = datetime.combine(day_d - timedelta(days=14), datetime.min.time(), tzinfo=timezone.utc)

    items_raw = load_cache_items(cache_root)
    if not items_raw and cache_only:
        raise FileNotFoundError(
            f"News cache empty or missing under {cache_dir(cache_root)}. "
            "Run: python fetch_news.py ingest --backfill-range FROM TO"
        )

    selected: List[Dict[str, Any]] = []
    for it in items_raw:
        if it.get("source") == "fetch_error":
            continue
        pub = _parse_ts(it.get("published")) if it.get("published") else None
        if pub is None:
            continue
        if pub >= cutoff:
            continue  # no lookahead
        src = it.get("source") or "unknown"
        floor = ptr_lookback_floor if src == "politician_trades" else lookback_floor
        if pub < floor:
            continue
        if pub.date() > day_d:
            continue
        selected.append(
            _item(
                src,
                it.get("title") or "",
                it.get("url") or "",
                pub,
                it.get("summary") or "",
            )
        )

    # Prefer newest first, then cap per source (PTR is color — keep a short list)
    selected.sort(key=lambda x: x.get("published") or "", reverse=True)
    caps = {"politician_trades": 12}
    default_cap = per_source_cap
    by_source_n: Dict[str, int] = {}
    capped: List[Dict[str, Any]] = []
    seen: Set[Tuple[Any, Any]] = set()
    for it in selected:
        key = (it.get("source"), it.get("title"))
        if key in seen:
            continue
        seen.add(key)
        src = it["source"]
        lim = caps.get(src, default_cap)
        if by_source_n.get(src, 0) >= lim:
            continue
        by_source_n[src] = by_source_n.get(src, 0) + 1
        capped.append(it)

    if cache_only and not capped:
        # Still write an empty-ish pack but signal via mode; caller may treat as soft miss
        pass

    source_counts: Dict[str, int] = {}
    for it in capped:
        source_counts[it["source"]] = source_counts.get(it["source"], 0) + 1

    return {
        "date": day,
        "cutoff_utc": rth_open_utc_iso(day),
        "mode": "cache",
        "fetched_at": _iso_z(datetime.now(timezone.utc)),
        "source_counts": source_counts,
        "cache_items_scanned": len(items_raw),
        "items": capped,
    }


def build_day_pack(
    day: str,
    *,
    cache_root: Optional[Path] = None,
    cache_only: bool = True,
    out_dir: Optional[Path] = None,
    fixture: Optional[Path] = None,
) -> Tuple[Path, Dict[str, Any]]:
    if fixture:
        data = json.loads(fixture.read_text())
        data["date"] = day
        data.setdefault("cutoff_utc", rth_open_utc_iso(day))
        data.setdefault("mode", "fixture")
        path = write_news(day, data, out_dir=out_dir)
        return path, data

    pack = slice_day_from_cache(day, cache_root=cache_root, cache_only=cache_only)
    if cache_only and pack.get("cache_items_scanned", 0) == 0:
        raise FileNotFoundError(f"cache-only: no items in cache for build-day {day}")
    path = write_news(day, pack, out_dir=out_dir)
    return path, pack


def write_news(day: str, pack: Dict[str, Any], out_dir: Optional[Path] = None) -> Path:
    out = (out_dir or NEWS) / f"{day}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pack, indent=2) + "\n")
    return out


# ---------------------------------------------------------------------------
# Hour pack builder (cache-only) — Alpaca hourly consensus
# ---------------------------------------------------------------------------


def slice_hour_from_cache(
    day: date,
    hour: int,
    *,
    cache_root: Optional[Path] = None,
    cache_only: bool = True,
    per_source_cap: int = 40,
) -> Dict[str, Any]:
    """Filter cache items with published strictly before this hour's ET start."""
    cutoff = cutoff_utc(day, hour)
    as_of = as_of_iso(day, hour)
    lookback_floor = cutoff - timedelta(days=2)
    ptr_lookback_floor = cutoff - timedelta(days=14)

    items_raw = load_cache_items(cache_root)
    if not items_raw and cache_only:
        raise FileNotFoundError(
            f"News cache empty or missing under {cache_dir(cache_root)}. "
            "Run: python fetch_news.py ingest --live-feeds  (or --backfill-range …)"
        )

    selected: List[Dict[str, Any]] = []
    for it in items_raw:
        if it.get("source") == "fetch_error":
            continue
        pub = _parse_ts(it.get("published")) if it.get("published") else None
        if pub is None:
            continue
        if pub >= cutoff:
            continue  # no lookahead past hour start
        src = it.get("source") or "unknown"
        floor = ptr_lookback_floor if src == "politician_trades" else lookback_floor
        if pub < floor:
            continue
        selected.append(
            _item(
                src,
                it.get("title") or "",
                it.get("url") or "",
                pub,
                it.get("summary") or "",
            )
        )

    selected.sort(key=lambda x: x.get("published") or "", reverse=True)
    caps = {"politician_trades": 12}
    by_source_n: Dict[str, int] = {}
    capped: List[Dict[str, Any]] = []
    seen: Set[Tuple[Any, Any]] = set()
    for it in selected:
        key = (it.get("source"), it.get("title"))
        if key in seen:
            continue
        seen.add(key)
        src = it["source"]
        lim = caps.get(src, per_source_cap)
        if by_source_n.get(src, 0) >= lim:
            continue
        by_source_n[src] = by_source_n.get(src, 0) + 1
        capped.append(it)

    source_counts: Dict[str, int] = {}
    for it in capped:
        source_counts[it["source"]] = source_counts.get(it["source"], 0) + 1

    return {
        "as_of": as_of,
        "date": day.isoformat(),
        "hour_et": f"{hour:02d}",
        "cutoff_utc": _iso_z(cutoff),
        "mode": "cache",
        "fetched_at": _iso_z(datetime.now(timezone.utc)),
        "source_counts": source_counts,
        "cache_items_scanned": len(items_raw),
        "items": capped,
    }


def build_hour_pack(
    bucket: str,
    *,
    cache_root: Optional[Path] = None,
    cache_only: bool = True,
    utc: bool = False,
    fixture: Optional[Path] = None,
) -> Tuple[Path, Dict[str, Any]]:
    day, hour, as_of = parse_hour_bucket(bucket, utc=utc)
    out = hourly_news_path(day.isoformat(), hour)
    if fixture:
        data = json.loads(fixture.read_text())
        data["as_of"] = as_of
        data["date"] = day.isoformat()
        data["hour_et"] = f"{hour:02d}"
        data.setdefault("cutoff_utc", _iso_z(cutoff_utc(day, hour)))
        data.setdefault("mode", "fixture")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2) + "\n")
        return out, data

    pack = slice_hour_from_cache(day, hour, cache_root=cache_root, cache_only=cache_only)
    if cache_only and pack.get("cache_items_scanned", 0) == 0:
        raise FileNotFoundError(f"cache-only: no items in cache for build-hour {bucket}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pack, indent=2) + "\n")
    return out, pack


# ---------------------------------------------------------------------------
# Backward-compatible helpers used by run_backfill
# ---------------------------------------------------------------------------


def build_news_pack(
    day: str,
    mode: str = "auto",
    fixture: Optional[Path] = None,
    *,
    cache_only: bool = True,
) -> Dict[str, Any]:
    """Prefer cache-only day slice. Legacy live/gdelt modes only if cache_only=False."""
    if fixture:
        data = json.loads(fixture.read_text())
        data["date"] = day
        data.setdefault("cutoff_utc", rth_open_utc_iso(day))
        data.setdefault("mode", "fixture")
        return data

    if cache_only or mode in ("cache", "auto"):
        try:
            return slice_day_from_cache(day, cache_only=True)
        except FileNotFoundError:
            if cache_only or mode == "cache":
                raise
            # fall through only when explicitly allowing live (mode live/gdelt with cache_only=False)

    if mode == "live":
        # One-shot live into cache then slice — still avoids per-day hammer loops if ingest was done
        ingest_live_feeds()
        return slice_day_from_cache(day, cache_only=False)

    if mode == "gdelt":
        d = parse_day(day)
        ingest_gdelt_range(d, d)
        return slice_day_from_cache(day, cache_only=False)

    return slice_day_from_cache(day, cache_only=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="DayTrade news: batch ingest → local cache → cache-only day packs"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="Batch-pull upstream into state/news_cache/")
    p_ingest.add_argument(
        "--backfill-range",
        nargs=2,
        metavar=("FROM", "TO"),
        help="Inclusive YYYY-MM-DD range for batch historical ingest",
    )
    p_ingest.add_argument(
        "--via",
        choices=["gkg", "doc", "auto"],
        default="gkg",
        help="Historical source: gkg=GDELT file dumps (default, avoids DOC 429); doc=DOC API; auto=doc then gkg",
    )
    p_ingest.add_argument(
        "--live-feeds",
        action="store_true",
        help="Also grab current RSS + EDGAR once into cache",
    )
    p_ingest.add_argument(
        "--seed-day-packs",
        action="store_true",
        help="Import existing state/news/*.json into cache (no network)",
    )
    p_ingest.add_argument(
        "--politician-trades",
        action="store_true",
        help="Ingest US House STOCK Act PTR filings (official clerk FD zips)",
    )
    p_ingest.add_argument(
        "--skip-politician-trades",
        action="store_true",
        help="Do not auto-include politician trades during --backfill-range",
    )
    p_ingest.add_argument("--chunk-days", type=int, default=GDELT_CHUNK_DAYS)
    p_ingest.add_argument("--sleep", type=float, default=None, help="Pause between upstream requests")
    p_ingest.add_argument(
        "--domains",
        nargs="+",
        default=None,
        help="Override GDELT DOC domains (default: yahoo, marketwatch, sec.gov, reuters)",
    )
    p_ingest.add_argument("--cache-dir", type=Path, default=None)

    p_build = sub.add_parser("build-day", help="Build state/news/YYYY-MM-DD.json from cache only")
    p_build.add_argument("date", help="YYYY-MM-DD as_of trading day")
    p_build.add_argument(
        "--cache-only",
        action="store_true",
        default=True,
        help="Require cache (default); error if cache empty",
    )
    p_build.add_argument("--allow-empty-cache", action="store_true", help="Do not error on empty cache")
    p_build.add_argument("--from-fixture", type=Path)
    p_build.add_argument("--out-dir", type=Path, default=NEWS)
    p_build.add_argument("--cache-dir", type=Path, default=None)
    p_build.add_argument("--allow-non-trading-day", action="store_true")

    p_hour = sub.add_parser(
        "build-hour",
        help="Build state/hourly/YYYY-MM-DD/HH/news.json from cache only (cutoff=hour start ET)",
    )
    p_hour.add_argument("bucket", help="Hour bucket YYYY-MM-DDTHH (America/New_York by default)")
    p_hour.add_argument("--utc", action="store_true", help="Interpret HH as UTC")
    p_hour.add_argument("--allow-empty-cache", action="store_true")
    p_hour.add_argument("--from-fixture", type=Path)
    p_hour.add_argument("--cache-dir", type=Path, default=None)
    p_hour.add_argument(
        "--allow-non-rth",
        action="store_true",
        help="Allow hours outside 10–15 ET / non-trading days",
    )

    # Legacy single-flag interface → maps to build-day for compat
    p_legacy = sub.add_parser("fetch", help="(compat) build-day from cache; use ingest separately")
    p_legacy.add_argument("--date", required=True)
    p_legacy.add_argument("--mode", choices=["auto", "live", "gdelt", "cache"], default="cache")
    p_legacy.add_argument("--from-fixture", type=Path)
    p_legacy.add_argument("--out-dir", type=Path, default=NEWS)
    p_legacy.add_argument("--allow-non-trading-day", action="store_true")
    p_legacy.add_argument("--cache-only", action="store_true", default=True)

    args = p.parse_args(argv)

    if args.cmd == "ingest":
        results: Dict[str, Any] = {}
        if args.seed_day_packs:
            results["seed"] = seed_cache_from_day_packs(cache_root=args.cache_dir)
        if args.backfill_range:
            a, b = args.backfill_range
            start, end = parse_day(a), parse_day(b)
            if end < start:
                print("error: TO before FROM", file=sys.stderr)
                return 1
            via = args.via
            if via in ("doc", "auto"):
                results["gdelt_doc"] = ingest_gdelt_range(
                    start,
                    end,
                    cache_root=args.cache_dir,
                    chunk_days=args.chunk_days,
                    sleep_s=args.sleep if args.sleep is not None else GDELT_SLEEP,
                    domains=args.domains,
                )
                doc_ok = int(results["gdelt_doc"].get("requests_ok") or 0)
                doc_added = int(results["gdelt_doc"].get("items_added") or 0)
                if via == "auto" and doc_ok == 0 and doc_added == 0:
                    via = "gkg"  # fall through to dumps
                elif via == "doc":
                    via = None
            if via == "gkg":
                results["gdelt_gkg"] = ingest_gkg_range(
                    start,
                    end,
                    cache_root=args.cache_dir,
                    sleep_s=args.sleep if args.sleep is not None else GKG_SLEEP,
                )
            if not args.skip_politician_trades:
                results["politician_trades"] = ingest_politician_trades(
                    cache_root=args.cache_dir,
                    from_day=start,
                    to_day=end,
                )
        elif args.politician_trades:
            results["politician_trades"] = ingest_politician_trades(cache_root=args.cache_dir)
        if args.live_feeds:
            results["live"] = ingest_live_feeds(cache_root=args.cache_dir)
        if not results:
            print(
                "error: specify --backfill-range and/or --live-feeds and/or "
                "--seed-day-packs and/or --politician-trades",
                file=sys.stderr,
            )
            return 1
        print(json.dumps(results, indent=2))
        return 0

    if args.cmd == "build-hour":
        from hour_bucket import is_rth_consensus_hour

        try:
            day_h, hour_h, as_of_h = parse_hour_bucket(args.bucket, utc=args.utc)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if not args.allow_non_rth and not is_rth_consensus_hour(day_h, hour_h):
            print(
                f"error: {as_of_h} is outside RTH consensus hours (10–15 ET trading day); "
                "pass --allow-non-rth to override",
                file=sys.stderr,
            )
            return 1
        try:
            path, pack = build_hour_pack(
                args.bucket,
                cache_root=args.cache_dir,
                cache_only=not args.allow_empty_cache,
                utc=args.utc,
                fixture=args.from_fixture,
            )
        except FileNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "wrote": str(path),
                    "as_of": pack.get("as_of"),
                    "items": len(pack.get("items", [])),
                    "mode": pack.get("mode"),
                    "source_counts": pack.get("source_counts"),
                    "cache_items_scanned": pack.get("cache_items_scanned"),
                    "cutoff_utc": pack.get("cutoff_utc"),
                }
            )
        )
        return 0

    if args.cmd in ("build-day", "fetch"):
        day = args.date if args.cmd == "build-day" else args.date
        d = parse_day(day)
        if not args.allow_non_trading_day and not is_trading_day(d):
            print(f"error: {day} is not an NYSE trading day", file=sys.stderr)
            return 1
        cache_only = True
        if args.cmd == "build-day":
            cache_only = not args.allow_empty_cache
            fixture = args.from_fixture
            out_dir = args.out_dir
            cache_root = args.cache_dir
        else:
            cache_only = args.cache_only and args.mode in ("auto", "cache")
            fixture = args.from_fixture
            out_dir = args.out_dir
            cache_root = None
            if args.mode in ("live", "gdelt") and not cache_only:
                pack = build_news_pack(day, mode=args.mode, fixture=fixture, cache_only=False)
                path = write_news(day, pack, out_dir=out_dir)
                print(json.dumps({"wrote": str(path), "items": len(pack.get("items", [])), "mode": pack.get("mode")}))
                return 0
        try:
            path, pack = build_day_pack(
                day,
                cache_root=cache_root,
                cache_only=cache_only,
                out_dir=out_dir,
                fixture=fixture,
            )
        except FileNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "wrote": str(path),
                    "items": len(pack.get("items", [])),
                    "mode": pack.get("mode"),
                    "source_counts": pack.get("source_counts"),
                    "cache_items_scanned": pack.get("cache_items_scanned"),
                }
            )
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
