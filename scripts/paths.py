"""Resolve Project store paths relative to this scripts/ directory."""
from __future__ import annotations

from pathlib import Path

STORE_ROOT = Path(__file__).resolve().parent.parent
STATE = STORE_ROOT / "state"
DOCS = STORE_ROOT / "docs"
PROMPTS = STORE_ROOT / "prompts"
FIXTURES = STORE_ROOT / "fixtures"
SCRIPTS = STORE_ROOT / "scripts"

SIM_META = STATE / "sim-meta.json"
ROSTER = STATE / "roster.json"
LESSONS = STATE / "lessons" / "ledger.jsonl"
AGENTS = STATE / "agents"
MARKET = STATE / "market"
NEWS = STATE / "news"
NEWS_CACHE = STATE / "news_cache"
BATCHES = STATE / "batches"
HOURLY = STATE / "hourly"
BOOK = STATE / "book"
ALPACA = STATE / "alpaca"
BOOK_PORTFOLIO = BOOK / "portfolio.json"
ALPACA_CONFIG = ALPACA / "config.json"
SIGNALS = STATE / "signals"
SIGNALS_LATEST = SIGNALS / "latest.json"


def agent_dir(agent_id: str) -> Path:
    return AGENTS / agent_id


def portfolio_path(agent_id: str) -> Path:
    return agent_dir(agent_id) / "portfolio.json"


def journal_dir(agent_id: str) -> Path:
    return agent_dir(agent_id) / "journal"


def market_path(day: str) -> Path:
    return MARKET / f"{day}.json"


def news_path(day: str) -> Path:
    return NEWS / f"{day}.json"


def batch_path(day: str, agent_id: str) -> Path:
    return BATCHES / day / f"{agent_id}.json"


def hourly_dir(day: str, hour_or_slot: str | int) -> Path:
    slot = _normalize_slot(hour_or_slot)
    primary = HOURLY / day / slot
    if primary.exists():
        return primary
    # Legacy hour-only dirs (e.g. "14")
    if slot.endswith("00"):
        legacy = HOURLY / day / slot[:2]
        if legacy.exists():
            return legacy
    return primary


def _normalize_slot(hour_or_slot: str | int) -> str:
    if isinstance(hour_or_slot, int):
        return f"{hour_or_slot:02d}00"
    raw = str(hour_or_slot).strip()
    if len(raw) == 4 and raw.isdigit():
        return raw
    if raw.isdigit() and len(raw) <= 2:
        return f"{int(raw):02d}00"
    for sep in (":", "-"):
        if sep in raw:
            h, m = raw.split(sep, 1)
            return f"{int(h):02d}{int(m):02d}"
    return raw


def hourly_news_path(day: str, hour_or_slot: str | int) -> Path:
    return hourly_dir(day, hour_or_slot) / "news.json"


def hourly_proposal_path(day: str, hour_or_slot: str | int, agent_id: str) -> Path:
    return hourly_dir(day, hour_or_slot) / f"{agent_id}.json"


def hourly_pack_path(day: str, hour_or_slot: str | int, agent_id: str) -> Path:
    return hourly_dir(day, hour_or_slot) / f"{agent_id}.md"


def hourly_consensus_path(day: str, hour_or_slot: str | int) -> Path:
    return hourly_dir(day, hour_or_slot) / "consensus.json"


def hourly_signals_path(day: str, hour_or_slot: str | int) -> Path:
    return hourly_dir(day, hour_or_slot) / "signals.json"


def daily_dir(day: str) -> Path:
    return STATE / "daily" / day


def day_end_analysis_path(day: str) -> Path:
    return daily_dir(day) / "analysis.json"


def load_roster() -> dict:
    import json

    if not ROSTER.exists():
        return {"agents": {"A1": {"model_id": "grok-4.7"}}}
    text = ROSTER.read_text(encoding="utf-8-sig")
    data = json.loads(text)
    return data if isinstance(data, dict) else {"agents": {}}


def active_agent_ids(roster: dict | None = None) -> list[str]:
    """Agents in state/roster.json with a non-empty model_id (sorted). Not a hard-coded A1–A5 list."""
    r = roster if roster is not None else load_roster()
    agents = r.get("agents") if isinstance(r, dict) else None
    if not isinstance(agents, dict):
        return ["A1"]
    ids = sorted(
        aid
        for aid, meta in agents.items()
        if isinstance(meta, dict) and isinstance(meta.get("model_id"), str) and meta["model_id"].strip()
    )
    return ids or ["A1"]
