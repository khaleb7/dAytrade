"""Day recap site. Reads the account; never writes an order."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Config
from .recap import page


class Handler(BaseHTTPRequestHandler):
    config: Config

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._send(200, b'{"ok": true}', "application/json")
            return
        if path in ("/", "/recap"):
            self._send(200, page(self.config).encode("utf-8"), "text/html; charset=utf-8")
            return
        self._send(404, b'{"ok": false}', "application/json")


def serve(cfg: Config) -> ThreadingHTTPServer:
    Handler.config = cfg
    server = ThreadingHTTPServer((cfg.bind, cfg.port), Handler)
    print(f"[souper] http://{cfg.bind}:{cfg.port}", flush=True)
    return server
