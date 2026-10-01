"""SQLite store. Newstracker is the only writer."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from .clock import et_day


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  url TEXT,
  symbol TEXT,
  etag TEXT,
  next_eligible_at TEXT NOT NULL,
  last_fetched_at TEXT,
  last_error TEXT
);

CREATE TABLE IF NOT EXISTS articles (
  dedupe_key TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  published TEXT,
  summary TEXT,
  ingested_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS articles_published ON articles(published);
CREATE INDEX IF NOT EXISTS articles_source_published ON articles(source, published);

CREATE TABLE IF NOT EXISTS bars (
  symbol TEXT NOT NULL,
  ts TEXT NOT NULL,
  open REAL,
  high REAL,
  low REAL,
  close REAL,
  volume REAL,
  PRIMARY KEY (symbol, ts)
);

CREATE TABLE IF NOT EXISTS sessions (
  symbol TEXT NOT NULL,
  day TEXT NOT NULL,
  open REAL,
  high REAL,
  low REAL,
  close REAL,
  volume REAL,
  PRIMARY KEY (symbol, day)
);
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> datetime:
    raw = text.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quotes(session_day: str, session_rows: list[sqlite3.Row], minute_rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in session_rows:
        slot = by_symbol.setdefault(row["symbol"], {"days": []})
        slot["days"].append(row)
    for row in minute_rows:
        try:
            day = et_day(parse_iso(row["ts"]))
        except ValueError:
            continue
        if day != session_day:
            continue
        slot = by_symbol.setdefault(row["symbol"], {"days": []})
        mins = slot.setdefault("minutes", [])
        mins.append(row)
    quotes: list[dict[str, Any]] = []
    for symbol in sorted(by_symbol):
        slot = by_symbol[symbol]
        days = sorted(slot.get("days") or [], key=lambda r: r["day"])
        today = next((r for r in days if r["day"] == session_day), None)
        prior = next((r for r in reversed(days) if r["day"] < session_day), None)
        minutes = slot.get("minutes") or []
        open_ = _num(today["open"]) if today is not None else None
        high = _num(today["high"]) if today is not None else None
        low = _num(today["low"]) if today is not None else None
        last = _num(today["close"]) if today is not None else None
        last_ts = None
        if minutes:
            if open_ is None:
                open_ = _num(minutes[0]["open"])
            highs = [v for v in (_num(r["high"]) for r in minutes) if v is not None]
            lows = [v for v in (_num(r["low"]) for r in minutes) if v is not None]
            if highs:
                high = max([v for v in [high, *highs] if v is not None])
            if lows:
                low = min([v for v in [low, *lows] if v is not None])
            last = _num(minutes[-1]["close"])
            last_ts = minutes[-1]["ts"]
        quotes.append(
            {
                "symbol": symbol,
                "session_open": open_,
                "session_high": high,
                "session_low": low,
                "last": last,
                "prior_close": _num(prior["close"]) if prior is not None else None,
                "last_ts": last_ts,
            }
        )
    return quotes


class Store:
    def __init__(self, path: str) -> None:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def seed_source(
        self,
        source_id: str,
        kind: str,
        *,
        url: str = "",
        symbol: str = "",
    ) -> None:
        now = iso_z(utc_now() - timedelta(seconds=1))
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sources (id, kind, url, symbol, next_eligible_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  kind=excluded.kind,
                  url=excluded.url,
                  symbol=excluded.symbol
                """,
                (source_id, kind, url, symbol, now),
            )
            self._conn.commit()

    def due_source(self, now: datetime) -> sqlite3.Row | None:
        stamp = iso_z(now)
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM sources
                WHERE next_eligible_at <= ?
                ORDER BY CASE WHEN kind = 'edgar' THEN 0 ELSE 1 END,
                         next_eligible_at ASC,
                         id ASC
                LIMIT 1
                """,
                (stamp,),
            ).fetchone()
        return row

    def next_eligible(self) -> datetime | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT MIN(next_eligible_at) AS t FROM sources"
            ).fetchone()
        if row is None or not row["t"]:
            return None
        return parse_iso(row["t"])

    def mark_source(
        self,
        source_id: str,
        *,
        next_eligible_at: datetime,
        error: str | None,
        etag: str | None = None,
    ) -> None:
        with self._lock:
            if etag is None:
                self._conn.execute(
                    """
                    UPDATE sources
                    SET next_eligible_at=?, last_fetched_at=?, last_error=?
                    WHERE id=?
                    """,
                    (iso_z(next_eligible_at), iso_z(utc_now()), error, source_id),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE sources
                    SET next_eligible_at=?, last_fetched_at=?, last_error=?, etag=?
                    WHERE id=?
                    """,
                    (iso_z(next_eligible_at), iso_z(utc_now()), error, etag, source_id),
                )
            self._conn.commit()

    def source_etag(self, source_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT etag FROM sources WHERE id=?", (source_id,)
            ).fetchone()
        if row is None:
            return None
        return row["etag"]

    def upsert_articles(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        ingested = iso_z(utc_now())
        inserted = 0
        with self._lock:
            for row in rows:
                url = (row.get("url") or "").strip()
                source = row["source"]
                title = row["title"]
                published = row.get("published") or ""
                key = url if url else f"{source}|{title}|{published}"
                cur = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO articles
                      (dedupe_key, source, title, url, published, summary, ingested_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        key,
                        source,
                        title,
                        url,
                        published or None,
                        (row.get("summary") or "")[:500],
                        ingested,
                    ),
                )
                inserted += cur.rowcount
            self._conn.commit()
        return inserted

    def upsert_bars(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        n = 0
        with self._lock:
            for row in rows:
                cur = self._conn.execute(
                    """
                    INSERT INTO bars (symbol, ts, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol, ts) DO UPDATE SET
                      open=excluded.open,
                      high=excluded.high,
                      low=excluded.low,
                      close=excluded.close,
                      volume=excluded.volume
                    """,
                    (
                        row["symbol"],
                        row["ts"],
                        row.get("open"),
                        row.get("high"),
                        row.get("low"),
                        row.get("close"),
                        row.get("volume"),
                    ),
                )
                n += cur.rowcount
            self._conn.commit()
        return n

    def upsert_sessions(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        n = 0
        with self._lock:
            for row in rows:
                cur = self._conn.execute(
                    """
                    INSERT INTO sessions (symbol, day, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol, day) DO UPDATE SET
                      open=excluded.open,
                      high=excluded.high,
                      low=excluded.low,
                      close=excluded.close,
                      volume=excluded.volume
                    """,
                    (
                        row["symbol"],
                        row["day"],
                        row.get("open"),
                        row.get("high"),
                        row.get("low"),
                        row.get("close"),
                        row.get("volume"),
                    ),
                )
                n += cur.rowcount
            self._conn.commit()
        return n

    def context(
        self,
        as_of: datetime,
        *,
        per_source: int = 40,
        lookback_days: int = 2,
        since: datetime | None = None,
    ) -> dict[str, Any]:
        start_dt = as_of - timedelta(days=lookback_days)
        if since is not None and since > start_dt:
            start_dt = since
        start = iso_z(start_dt)
        cutoff = iso_z(as_of)
        with self._lock:
            article_rows = self._conn.execute(
                """
                SELECT source, title, url, published, summary
                FROM articles
                WHERE published IS NOT NULL AND published >= ? AND published < ?
                ORDER BY published DESC
                """,
                (start, cutoff),
            ).fetchall()
            bar_rows = self._conn.execute(
                """
                SELECT b.symbol, b.ts, b.open, b.high, b.low, b.close, b.volume
                FROM bars b
                INNER JOIN (
                  SELECT symbol, MAX(ts) AS ts
                  FROM bars
                  WHERE ts < ?
                  GROUP BY symbol
                ) latest ON latest.symbol = b.symbol AND latest.ts = b.ts
                ORDER BY b.symbol
                """,
                (cutoff,),
            ).fetchall()
            session_rows = self._conn.execute(
                "SELECT symbol, day, open, high, low, close FROM sessions"
            ).fetchall()
            minute_rows = self._conn.execute(
                """
                SELECT symbol, ts, open, high, low, close
                FROM bars
                WHERE ts >= ? AND ts < ?
                ORDER BY symbol, ts
                """,
                (iso_z(as_of - timedelta(days=3)), cutoff),
            ).fetchall()
            counts = self._conn.execute(
                "SELECT (SELECT COUNT(*) FROM articles), (SELECT COUNT(*) FROM bars)"
            ).fetchone()
        kept: list[dict[str, Any]] = []
        seen: dict[str, int] = {}
        for row in article_rows:
            source = row["source"]
            n = seen.get(source, 0)
            if n >= per_source:
                continue
            seen[source] = n + 1
            kept.append(
                {
                    "source": source,
                    "title": row["title"],
                    "url": row["url"],
                    "published": row["published"],
                    "summary": row["summary"] or "",
                }
            )
        bars = [
            {
                "symbol": row["symbol"],
                "ts": row["ts"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            }
            for row in bar_rows
        ]
        session_day = et_day(as_of)
        quotes = _quotes(session_day, session_rows, minute_rows)
        return {
            "as_of": cutoff,
            "since": iso_z(start_dt) if since is not None else None,
            "articles": kept,
            "bars": bars,
            "quotes": quotes,
            "article_count": counts[0] if counts else 0,
            "bar_count": counts[1] if counts else 0,
        }

    def counts(self) -> dict[str, int]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM articles) AS articles,
                  (SELECT COUNT(*) FROM bars) AS bars,
                  (SELECT COUNT(*) FROM sources) AS sources
                """
            ).fetchone()
        return {
            "articles": int(row["articles"]),
            "bars": int(row["bars"]),
            "sources": int(row["sources"]),
        }
