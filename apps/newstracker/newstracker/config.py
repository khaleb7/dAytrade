"""Environment configuration. Secrets come from the process environment only."""

from __future__ import annotations

import os
from dataclasses import dataclass


USER_AGENT = "DayTradeSimulator/1.0 (+cursor-project; research)"

RSS_FEEDS = (
    ("reuters", "https://feeds.reuters.com/reuters/businessNews"),
    ("yahoo_finance", "https://finance.yahoo.com/news/rssindex"),
    ("marketwatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
)

EDGAR_ATOM = (
    "https://www.sec.gov/cgi-bin/browse-edgar?"
    "action=getcurrent&type=8-K&company=&dateb=&owner=include&count=40&output=atom"
)

DEFAULT_SYMBOLS = (
    "SPY",
    "QQQ",
    "IWM",
    "VTI",
    "TLT",
    "USO",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "DIA",
    "XLF",
    "XLE",
    "GLD",
    "TSLA",
    "AVGO",
    "AMD",
    "JPM",
    "V",
    "LLY",
    "COST",
    "XOM",
    "WMT",
    "NFLX",
)


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return float(raw)


@dataclass(frozen=True)
class Config:
    db_path: str
    bind: str
    port: int
    cycle_sleep_s: float
    feed_interval_s: float
    bar_interval_s: float
    backoff_s: float
    rate_limit_s: float
    symbols: tuple[str, ...]
    alpaca_data_url: str
    alpaca_feed: str
    alpaca_key: str
    alpaca_secret: str

    @property
    def alpaca_configured(self) -> bool:
        return bool(self.alpaca_key and self.alpaca_secret)


def load_config() -> Config:
    symbols_raw = os.environ.get("NEWSTRACKER_SYMBOLS", "").strip()
    if symbols_raw:
        symbols = tuple(s.strip().upper() for s in symbols_raw.split(",") if s.strip())
    else:
        symbols = DEFAULT_SYMBOLS
    return Config(
        db_path=os.environ.get("NEWSTRACKER_DB", "/data/newstracker.db"),
        bind=os.environ.get("NEWSTRACKER_BIND", "0.0.0.0"),
        port=_int("NEWSTRACKER_PORT", 8080),
        cycle_sleep_s=_float("NEWSTRACKER_CYCLE_SLEEP", 60),
        feed_interval_s=_float("NEWSTRACKER_FEED_INTERVAL", 300),
        bar_interval_s=_float("NEWSTRACKER_BAR_INTERVAL", 180),
        backoff_s=_float("NEWSTRACKER_ERROR_BACKOFF", 300),
        rate_limit_s=_float("NEWSTRACKER_RATE_LIMIT_BACKOFF", 900),
        symbols=symbols,
        alpaca_data_url=os.environ.get(
            "NEWSTRACKER_ALPACA_DATA_URL", "https://data.alpaca.markets"
        ).rstrip("/"),
        alpaca_feed=os.environ.get("NEWSTRACKER_ALPACA_FEED", "iex"),
        alpaca_key=os.environ.get("APCA_API_KEY_ID", "").strip(),
        alpaca_secret=os.environ.get("APCA_API_SECRET_KEY", "").strip(),
    )
