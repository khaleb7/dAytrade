"""Read the Newstracker context API. No writes."""

from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import urlopen


def fetch_context(base_url: str, as_of: str, lookback_days: int) -> dict:
    query = urlencode({"as_of": as_of, "lookback_days": str(lookback_days)})
    url = f"{base_url.rstrip('/')}/v1/context?{query}"
    with urlopen(url, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload.get("articles"), list):
        raise ValueError("Newstracker context missing articles")
    return payload
