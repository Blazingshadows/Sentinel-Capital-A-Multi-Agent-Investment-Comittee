"""News headline ingestion for the News & Sentiment Agent. Public RSS feeds
only (no paid API required); results are cached per symbol so the Sentiment
agent and Replay Mode can both read the same corpus."""

import json
from pathlib import Path

import feedparser

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "news_corpus"

NEWS_FEEDS = [
    "https://www.moneycontrol.com/rss/marketreports.xml",
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
]

# Small alias table so "TCS" also matches headlines mentioning "Tata Consultancy".
COMPANY_ALIASES = {
    "RELIANCE": ["reliance"],
    "TCS": ["tcs", "tata consultancy"],
    "HDFCBANK": ["hdfc bank"],
    "INFY": ["infosys"],
    "ICICIBANK": ["icici bank"],
    "SBIN": ["sbi", "state bank of india"],
    "TATAMOTORS": ["tata motors"],
    "ITC": ["itc"],
    "LT": ["l&t", "larsen"],
    "ADANIENT": ["adani enterprises", "adani ent"],
}


def _cache_path(symbol: str) -> Path:
    return DATA_DIR / f"{symbol}.json"


def fetch_headlines(symbol: str, limit: int = 10, use_cache_on_failure: bool = True) -> list[str]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(symbol)
    aliases = COMPANY_ALIASES.get(symbol, [symbol.lower()])

    try:
        headlines: list[str] = []
        for feed_url in NEWS_FEEDS:
            parsed = feedparser.parse(feed_url)
            if parsed.bozo and not parsed.entries:
                continue
            for entry in parsed.entries:
                title = entry.get("title", "")
                if any(alias in title.lower() for alias in aliases):
                    headlines.append(title)

        if not headlines:
            raise ValueError(f"no headlines found for {symbol}")

        headlines = headlines[:limit]
        cache_path.write_text(json.dumps(headlines))
        return headlines
    except Exception:
        if use_cache_on_failure and cache_path.exists():
            return json.loads(cache_path.read_text())[:limit]
        return []
