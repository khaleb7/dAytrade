"""Startup Discord ping. A missing URL or HTTP error never stops the process."""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone


def notify(title: str, body: str, username: str) -> None:
    raw = (os.environ.get("DAYTRADE_DISCORD_WEBHOOK_URL") or "").strip()
    if not raw:
        print("[discord] webhook unset", flush=True)
        return
    if "discord.com/api/webhooks/" not in raw and "discordapp.com/api/webhooks/" not in raw:
        print("[discord] ignoring invalid webhook URL shape", flush=True)
        return
    payload = {
        "username": username[:80],
        "embeds": [
            {
                "title": title[:240],
                "description": body[:1800],
                "color": 0x3498DB,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        ],
    }
    req = urllib.request.Request(
        raw,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "DayTrade/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            status = int(getattr(resp, "status", 204) or 204)
        if 200 <= status < 300:
            print("[discord] ping sent", flush=True)
        else:
            print(f"[discord] webhook HTTP {status} (soft-fail)", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[discord] webhook error (soft-fail): {type(e).__name__}", flush=True)
