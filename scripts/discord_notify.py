"""Discord webhook helper for Python fallback path (soft-fail).

Env: DAYTRADE_DISCORD_WEBHOOK_URL — never commit the secret.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ENV = "DAYTRADE_DISCORD_WEBHOOK_URL"


def _url() -> Optional[str]:
    raw = (os.environ.get(ENV) or "").strip()
    if not raw:
        return None
    if "discord.com/api/webhooks/" not in raw and "discordapp.com/api/webhooks/" not in raw:
        print("[discord] ignoring invalid webhook URL shape", flush=True)
        return None
    return raw


def notify(
    title: str,
    body: str = "",
    *,
    kind: str = "info",
    ok: Optional[bool] = None,
    fields: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    url = _url()
    if not url:
        return False
    if ok is False or kind == "issue":
        color = 0xE74C3C
    elif kind == "submit" and ok:
        color = 0x2ECC71
    elif kind == "day_end":
        color = 0x9B59B6
    elif kind == "tick_start":
        color = 0x3498DB
    elif kind == "consensus":
        color = 0xF39C12
    else:
        color = 0x95A5A6
    embed: Dict[str, Any] = {
        "title": title[:240],
        "color": color,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "footer": {"text": "DayTrade RTH"},
    }
    if body:
        embed["description"] = body[:1800]
    if fields:
        embed["fields"] = [
            {
                "name": str(f.get("name", ""))[:100],
                "value": (str(f.get("value", "")) or "—")[:500],
                "inline": bool(f.get("inline")),
            }
            for f in fields[:8]
        ]
    data = json.dumps({"username": "DayTrade", "embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "DayTrade/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return 200 <= int(getattr(resp, "status", 204) or 204) < 300
    except Exception as e:  # noqa: BLE001
        print(f"[discord] webhook error (soft-fail): {e}", flush=True)
        return False


if __name__ == "__main__":
    import sys

    ok = notify("DayTrade Discord test", "If you see this, the webhook env is working.", kind="info")
    print(json.dumps({"ok": ok, "configured": bool(_url())}))
    raise SystemExit(0 if ok or not _url() else 1)
