"""Serve the day recap. No publisher and no orders."""

from __future__ import annotations

from .config import load_config
from .discord import notify
from .httpapi import serve


def main() -> None:
    cfg = load_config()
    server = serve(cfg)
    notify("SouperMarket started", "Serving the day recap.", "SouperMarket")
    try:
        server.serve_forever()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
