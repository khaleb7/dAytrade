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


def hourly_dir(day: str, hour: str | int) -> Path:
    return HOURLY / day / f"{int(hour):02d}"


def hourly_news_path(day: str, hour: str | int) -> Path:
    return hourly_dir(day, hour) / "news.json"


def hourly_proposal_path(day: str, hour: str | int, agent_id: str) -> Path:
    return hourly_dir(day, hour) / f"{agent_id}.json"


def hourly_pack_path(day: str, hour: str | int, agent_id: str) -> Path:
    return hourly_dir(day, hour) / f"{agent_id}.md"


def hourly_consensus_path(day: str, hour: str | int) -> Path:
    return hourly_dir(day, hour) / "consensus.json"
