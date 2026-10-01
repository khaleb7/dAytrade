"""Read API for Daytrader. Writes stay on the poller."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .db import Store, parse_iso


class Handler(BaseHTTPRequestHandler):
    store: Store

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            counts = self.store.counts()
            self._send(200, {"ok": True, **counts})
            return
        if parsed.path == "/v1/context":
            qs = parse_qs(parsed.query)
            raw = (qs.get("as_of") or [""])[0].strip()
            if not raw:
                self._send(400, {"error": "as_of is required"})
                return
            try:
                as_of = parse_iso(raw)
            except ValueError:
                self._send(400, {"error": "as_of must be ISO-8601"})
                return
            lookback = 2
            raw_lb = (qs.get("lookback_days") or [""])[0].strip()
            if raw_lb:
                try:
                    lookback = int(raw_lb)
                except ValueError:
                    self._send(400, {"error": "lookback_days must be an integer"})
                    return
                if lookback < 1 or lookback > 14:
                    self._send(400, {"error": "lookback_days must be 1..14"})
                    return
            since = None
            raw_since = (qs.get("since") or [""])[0].strip()
            if raw_since:
                try:
                    since = parse_iso(raw_since)
                except ValueError:
                    self._send(400, {"error": "since must be ISO-8601"})
                    return
            self._send(200, self.store.context(as_of, lookback_days=lookback, since=since))
            return
        self._send(404, {"error": "not found"})


def serve(store: Store, bind: str, port: int) -> ThreadingHTTPServer:
    Handler.store = store
    server = ThreadingHTTPServer((bind, port), Handler)
    print(f"[newstracker] http://{bind}:{port}", flush=True)
    return server
