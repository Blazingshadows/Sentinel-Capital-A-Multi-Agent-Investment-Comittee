"""NSE discovery universe (a data asset, not logic).

`universe/nse_universe.json` is a list of `{symbol, sector, stock_code}`
entries. Sector is carried here because Breeze is a trading API with no
fundamentals/sector data (see `config.WATCHLIST_FUNDAMENTALS`), so the
subsystem owns its own sector map rather than depending on a live lookup.

`stock_code` is Breeze's per-symbol code (e.g. RELIANCE -> "RELIND"), which is
*not* the NSE tradingsymbol. Only symbols with a verified `stock_code` are
live-fetchable; `register_breeze_codes()` merges them into
`config.BREEZE_STOCK_CODE_MAP` so `prices.fetch_ohlcv` can resolve them, and
`load_universe(fetchable_only=True)` restricts the scan to those. Add verified
codes to widen the live universe. Tests inject an in-memory provider and so
exercise the full breadth without needing any Breeze mapping.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.committee.discovery.utils import dedupe_preserve_order

UNIVERSE_PATH = Path(__file__).resolve().parent / "universe" / "nse_universe.json"


def _load_entries(path: str | Path | None = None) -> list[dict]:
    resolved = Path(path) if path else UNIVERSE_PATH
    if not resolved.exists():
        from backend.committee.config import WATCHLIST, WATCHLIST_FUNDAMENTALS, BREEZE_STOCK_CODE_MAP

        return [
            {"symbol": s, "sector": WATCHLIST_FUNDAMENTALS.get(s, {}).get("sector"),
             "stock_code": BREEZE_STOCK_CODE_MAP.get(s)}
            for s in WATCHLIST
        ]
    raw = json.loads(resolved.read_text())
    return raw["symbols"] if isinstance(raw, dict) else raw


def load_universe(path: str | Path | None = None, fetchable_only: bool = False) -> list[str]:
    """De-duplicated, order-stable symbol list. With `fetchable_only=True`,
    restrict to symbols that have a Breeze `stock_code` (else the live fetch
    would just fail and be skipped)."""
    entries = _load_entries(path)
    symbols = (
        str(e["symbol"]).strip().upper()
        for e in entries
        if str(e.get("symbol", "")).strip() and (not fetchable_only or e.get("stock_code"))
    )
    return dedupe_preserve_order(symbols)


def load_sector_map(path: str | Path | None = None) -> dict[str, str | None]:
    return {str(e["symbol"]).strip().upper(): e.get("sector") for e in _load_entries(path) if e.get("symbol")}


def load_breeze_codes(path: str | Path | None = None) -> dict[str, str]:
    return {
        str(e["symbol"]).strip().upper(): e["stock_code"]
        for e in _load_entries(path)
        if e.get("symbol") and e.get("stock_code")
    }


def register_breeze_codes(path: str | Path | None = None) -> int:
    """Merge the universe's Breeze stock_codes into `config.BREEZE_STOCK_CODE_MAP`
    (without overwriting existing entries) so `prices.fetch_ohlcv` can resolve
    universe symbols. Returns how many codes were added."""
    from backend.committee.config import BREEZE_STOCK_CODE_MAP

    added = 0
    for symbol, code in load_breeze_codes(path).items():
        if symbol not in BREEZE_STOCK_CODE_MAP:
            BREEZE_STOCK_CODE_MAP[symbol] = code
            added += 1
    return added
