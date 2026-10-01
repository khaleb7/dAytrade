"""Environment configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


@dataclass(frozen=True)
class Config:
    db_path: str
    bind: str
    port: int
    newstracker_url: str
    publish_hour_et: int
    poll_s: float
    cursor_api_key: str
    model: str
    work_dir: str


def load_config() -> Config:
    return Config(
        db_path=os.environ.get("SOUPER_DB", "/data/souper.db"),
        bind=os.environ.get("SOUPER_BIND", "0.0.0.0"),
        port=_int("SOUPER_PORT", 8080),
        newstracker_url=os.environ.get(
            "NEWSTRACKER_URL", "http://newstracker.daytrade.svc.cluster.local:8080"
        ).rstrip("/"),
        publish_hour_et=_int("SOUPER_PUBLISH_HOUR_ET", 17),
        poll_s=float(os.environ.get("SOUPER_POLL_SECONDS", "60") or "60"),
        cursor_api_key=os.environ.get("CURSOR_API_KEY", "").strip(),
        model=os.environ.get("SOUPER_MODEL", "composer-2.5").strip() or "composer-2.5",
        work_dir=os.environ.get("SOUPER_WORK", "/work"),
    )
