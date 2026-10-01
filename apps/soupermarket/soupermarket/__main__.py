"""Serve the paper and file a new edition after the Eastern publish hour."""

from __future__ import annotations

import threading

from .config import load_config
from .discord import notify
from .httpapi import serve
from .publish import run_publisher
from .store import Store


def main() -> None:
    cfg = load_config()
    store = Store(cfg.db_path)
    threading.Thread(target=run_publisher, args=(store, cfg), name="publisher", daemon=True).start()
    server = serve(store, cfg.bind, cfg.port, cfg.publish_hour_et)
    notify(
        "SouperMarket started",
        f"Serving Souper Intelligence on {cfg.bind}:{cfg.port}.",
        "SouperMarket",
    )
    try:
        server.serve_forever()
    finally:
        server.shutdown()
        store.close()


if __name__ == "__main__":
    main()
