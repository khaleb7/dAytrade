"""Paced poller: one source per cycle, then sleep. 429s push next_eligible_at forward."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from .config import EDGAR_ATOM, RSS_FEEDS, Config
from .db import Store, iso_z, utc_now
from .fetch import fetch_bars, fetch_feed


def seed(store: Store, cfg: Config) -> None:
    for name, url in RSS_FEEDS:
        store.seed_source(name, "rss", url=url)
    store.seed_source("sec_edgar", "edgar", url=EDGAR_ATOM)
    if not cfg.alpaca_configured:
        print("[newstracker] APCA keys unset; skipping Alpaca bar sources", flush=True)
        return
    for symbol in cfg.symbols:
        store.seed_source(f"bar:{symbol}", "alpaca_bar", symbol=symbol)


def _eligible_after(cfg: Config, kind: str, result_error: str | None, retry_after_s: float | None) -> datetime:
    now = utc_now()
    if result_error and retry_after_s is not None:
        return now + timedelta(seconds=max(retry_after_s, cfg.rate_limit_s))
    if result_error and ("429" in result_error or "rate limit" in result_error.lower()):
        return now + timedelta(seconds=cfg.rate_limit_s)
    if result_error:
        return now + timedelta(seconds=cfg.backoff_s)
    if kind == "alpaca_bar":
        return now + timedelta(seconds=cfg.bar_interval_s)
    return now + timedelta(seconds=cfg.feed_interval_s)


def poll_once(store: Store, cfg: Config) -> str:
    """Fetch the next due source. Returns a one-line status."""
    row = store.due_source(utc_now())
    if row is None:
        nxt = store.next_eligible()
        if nxt is None:
            time.sleep(cfg.cycle_sleep_s)
            return "idle: no sources"
        wait = (nxt - utc_now()).total_seconds()
        time.sleep(min(max(wait, 1.0), cfg.cycle_sleep_s))
        return f"idle until {iso_z(nxt)}"

    source_id = row["id"]
    kind = row["kind"]
    if kind == "alpaca_bar":
        result = fetch_bars(cfg, row["symbol"])
    else:
        result = fetch_feed(row["url"], source_id, row["etag"])

    if result.articles:
        store.upsert_articles(result.articles)
    if result.bars:
        store.upsert_bars(result.bars)
    store.mark_source(
        source_id,
        next_eligible_at=_eligible_after(cfg, kind, result.error, result.retry_after_s),
        error=result.error,
        etag=result.etag if result.etag is not None else None,
    )
    if result.error:
        print(f"[newstracker] {source_id} error: {result.error}", flush=True)
    else:
        print(
            f"[newstracker] {source_id} articles={len(result.articles)} bars={len(result.bars)}",
            flush=True,
        )
    time.sleep(cfg.cycle_sleep_s)
    return source_id


def run_forever(store: Store, cfg: Config) -> None:
    seed(store, cfg)
    print(
        f"[newstracker] polling db={cfg.db_path} cycle_sleep={cfg.cycle_sleep_s}s",
        flush=True,
    )
    while True:
        try:
            poll_once(store, cfg)
        except Exception as e:  # keep the process up; one bad source must not exit
            print(f"[newstracker] cycle error: {e}", flush=True)
            time.sleep(cfg.cycle_sleep_s)
