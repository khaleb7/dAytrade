"""Issued editions. SouperMarket is the only writer."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS issues (
  edition_date TEXT PRIMARY KEY,
  issue_number INTEGER NOT NULL,
  body_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


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

    def has(self, edition_date: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM issues WHERE edition_date=?", (edition_date,)
            ).fetchone()
        return row is not None

    def put(self, edition_date: str, body: dict[str, Any], created_at: str) -> dict[str, Any]:
        with self._lock:
            existing = self._conn.execute(
                "SELECT issue_number, body_json, created_at FROM issues WHERE edition_date=?",
                (edition_date,),
            ).fetchone()
            if existing is not None:
                body = json.loads(existing["body_json"])
                body["issue_number"] = existing["issue_number"]
                return body
            number = self._conn.execute("SELECT COALESCE(MAX(issue_number), 0) + 1 FROM issues").fetchone()[0]
            body = dict(body)
            body["issue_number"] = number
            body["edition_date"] = edition_date
            self._conn.execute(
                "INSERT INTO issues (edition_date, issue_number, body_json, created_at) VALUES (?, ?, ?, ?)",
                (edition_date, number, json.dumps(body), created_at),
            )
            self._conn.commit()
        return body

    def get(self, edition_date: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT body_json FROM issues WHERE edition_date=?", (edition_date,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["body_json"])

    def dates(self) -> list[str]:
        """Newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT edition_date FROM issues ORDER BY edition_date DESC"
            ).fetchall()
        return [row["edition_date"] for row in rows]

    def latest(self) -> dict[str, Any] | None:
        dates = self.dates()
        if not dates:
            return None
        return self.get(dates[0])
