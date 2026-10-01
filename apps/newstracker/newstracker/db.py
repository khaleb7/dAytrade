"""SQLite store. Newstracker is the only writer."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any


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
                ORDER BY next_eligible_at ASC, id ASC
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

    def context(self, as_of: datetime, *, per_source: int = 40, lookback_days: int = 2) -> dict[str, Any]:
        start = iso_z(as_of - timedelta(days=lookback_days))
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
        return {
            "as_of": cutoff,
            "articles": kept,
            "bars": bars,
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
