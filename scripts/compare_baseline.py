"""Compares the committee against the vectorbt SMA-crossover baseline, one
watchlist symbol at a time (matched cash, matched cost assumptions, and the
exact same stats methodology), then reports the average across symbols.

Per-symbol rather than one multi-asset portfolio because the committee
already replays each symbol as its own isolated cycle sequence — building a
single interleaved multi-asset equity curve would need a common timeline
across symbols, which is a bigger, separately-worth-doing piece of work.
A per-symbol comparison is still a fair, honest apples-to-apples test: same
price series, same cash, same cost assumptions, same metric formulas.

Usage:
    python scripts/compare_baseline.py
"""

import asyncio
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.committee.baseline.metrics import compute_returns_stats  # noqa: E402
from backend.committee.baseline.vectorbt_baseline import build_price_panel, run_sma_crossover_baseline  # noqa: E402
from backend.committee.config import BUYING_POWER, WATCHLIST  # noqa: E402
from backend.committee.execution.portfolio import Portfolio  # noqa: E402
from backend.committee.market_data.context import fetch_fundamentals  # noqa: E402
from backend.committee.market_data.news import fetch_headlines  # noqa: E402
from backend.committee.orchestration.cycle import process_context  # noqa: E402
from backend.committee.persistence.db import init_db, make_engine, make_session_factory  # noqa: E402
from backend.committee.replay.player import ReplayFeed, load_cached_ohlcv  # noqa: E402

INTERVAL = "15m"


async def run_committee_equity_curve(symbol: str) -> pd.Series:
    """Single-symbol replay with a portfolio snapshot after every bar, so the
    resulting equity curve is directly comparable to the baseline's."""
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    session = make_session_factory(engine)()
    portfolio = Portfolio()

    ohlcv = load_cached_ohlcv(symbol, interval=INTERVAL)
    try:
        headlines = fetch_headlines(symbol)
    except Exception:
        headlines = []
    fundamentals, sector = fetch_fundamentals(symbol)
    feed = ReplayFeed(symbol=symbol, ohlcv=ohlcv, headlines=headlines, fundamentals=fundamentals, sector=sector)

    values: dict = {}
    while feed.has_next():
        context = feed.next_context()
        cycle_ts = pd.Timestamp(context.ohlcv.index[-1]).to_pydatetime()
        _, price = process_context(session, portfolio, context, cycle_ts=cycle_ts)
        snapshot = portfolio.mark_to_market({symbol: price})
        values[cycle_ts] = snapshot.portfolio_value

    session.close()
    return pd.Series(values)


def run_baseline_equity_curve(symbol: str) -> pd.Series:
    panel = build_price_panel([symbol], interval=INTERVAL)
    portfolio = run_sma_crossover_baseline(panel, init_cash=BUYING_POWER)
    return portfolio.value()[symbol]


def compare_symbol(symbol: str) -> pd.DataFrame | None:
    print(f"\n=== {symbol} ===")
    try:
        baseline_values = run_baseline_equity_curve(symbol)
        committee_values = asyncio.run(run_committee_equity_curve(symbol))
    except Exception as exc:
        print(f"  skipped: {exc}")
        return None

    baseline_stats = compute_returns_stats(baseline_values)
    committee_stats = compute_returns_stats(committee_values)
    comparison = pd.DataFrame({"Baseline (SMA crossover)": baseline_stats, "Committee": committee_stats})
    print(comparison.to_string())
    return comparison


def main() -> None:
    all_comparisons = []
    for symbol in WATCHLIST:
        comparison = compare_symbol(symbol)
        if comparison is not None:
            all_comparisons.append(comparison)

    if not all_comparisons:
        print("\nNo symbols produced a valid comparison.")
        return

    numeric_rows = [c for c in all_comparisons]
    average = sum(c.apply(pd.to_numeric, errors="coerce") for c in numeric_rows) / len(numeric_rows)
    print(f"\n=== Average across {len(numeric_rows)} symbols ===")
    print(average.to_string())


if __name__ == "__main__":
    main()
