"""Newspaper site. Reads editions; the publisher is the only writer."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .html import render_issue, render_waiting
from .store import Store


class Handler(BaseHTTPRequestHandler):
    store: Store
    publish_hour: int

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _html(self, code: int, page: str) -> None:
        body = page.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            dates = self.store.dates()
            body = f'{{"ok": true, "issues": {len(dates)}}}'.encode("utf-8")
            self._json(200, body)
            return
        dates = self.store.dates()
        if path in ("/", "/issues"):
            latest = self.store.latest()
            if latest is None:
                self._html(200, render_waiting(self.publish_hour))
                return
            self._html(200, render_issue(latest, dates))
            return
        if path.startswith("/issues/"):
            edition = path.removeprefix("/issues/").strip("/")
            issue = self.store.get(edition)
            if issue is None:
                self._html(404, render_waiting(self.publish_hour))
                return
            self._html(200, render_issue(issue, dates))
            return
        self._html(404, render_waiting(self.publish_hour))


def serve(store: Store, bind: str, port: int, publish_hour: int) -> ThreadingHTTPServer:
    Handler.store = store
    Handler.publish_hour = publish_hour
    server = ThreadingHTTPServer((bind, port), Handler)
    print(f"[souper] http://{bind}:{port}", flush=True)
    return server
