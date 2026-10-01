"""Start the read API and the paced poller."""

from __future__ import annotations

import threading

from .config import load_config
from .db import Store
from .discord import notify
from .httpapi import serve
from .poll import run_forever, seed


def main() -> None:
    cfg = load_config()
    store = Store(cfg.db_path)
    seed(store, cfg)
    server = serve(store, cfg.bind, cfg.port)
    thread = threading.Thread(target=server.serve_forever, name="http", daemon=True)
    thread.start()
    notify("Newstracker started", f"Listening on {cfg.bind}:{cfg.port}.", "Newstracker")
    try:
        run_forever(store, cfg)
    finally:
        server.shutdown()
        store.close()


if __name__ == "__main__":
    main()
