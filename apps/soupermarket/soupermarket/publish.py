"""File one edition per Eastern day, after the publish hour."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from .clock import et_instant, iso_z, to_et
from .compose import compose
from .config import Config
from .desk import write_commentaries
from .store import Store
from .wire import fetch_context


def publish_edition(store: Store, cfg: Config, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(timezone.utc)
    et = to_et(now)
    edition = et.date()
    key = edition.isoformat()
    if store.has(key):
        return store.get(key)
    if et.hour < cfg.publish_hour_et:
        return None
    as_of = et_instant(edition, cfg.publish_hour_et, 0)
    day_start = et_instant(edition, 0, 0)
    payload = fetch_context(cfg.newstracker_url, iso_z(as_of), 7)
    articles = list(payload.get("articles") or [])
    if not articles:
        print("[souper] publish waiting: wire has no articles", flush=True)
        return None
    body = compose(
        edition=edition,
        as_of=as_of,
        day_start=day_start,
        articles=articles,
    )
    body["commentaries"] = write_commentaries(
        body["front"],
        body["week"],
        api_key=cfg.cursor_api_key,
        model=cfg.model,
        cwd=cfg.work_dir,
    )
    saved = store.put(key, body, iso_z(now))
    print(f"[souper] filed {key} no.{saved.get('issue_number')}", flush=True)
    return saved


def run_publisher(store: Store, cfg: Config) -> None:
    print(
        f"[souper] publisher hour={cfg.publish_hour_et} ET wire={cfg.newstracker_url}",
        flush=True,
    )
    while True:
        try:
            publish_edition(store, cfg)
        except Exception as e:
            print(f"[souper] publish skipped: {e}", flush=True)
        time.sleep(cfg.poll_s)
