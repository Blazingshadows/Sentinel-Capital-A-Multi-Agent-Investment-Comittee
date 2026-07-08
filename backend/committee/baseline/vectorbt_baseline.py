"""vectorbt-based SMA-crossover baseline — an established algotrading
framework's own backtesting engine and stats, run over the same watchlist,
so the committee's performance is judged against a credible, independently-
verifiable reference point rather than only against itself. A hand-rolled
backtest risks subtle bugs (lookahead, wrong position sizing, inconsistent
costs) that quietly bias a self-authored comparison; vectorbt's engine and
stats module are used by enough people that those classes of bugs are
already shaken out.
"""

import pandas as pd
import vectorbt as vbt

from backend.committee.config import BUYING_POWER, WATCHLIST
from backend.committee.market_data.prices import fetch_ohlcv

FAST_WINDOW = 20
SLOW_WINDOW = 50

# Blended approximation of the NSE intraday cost stack (brokerage + STT +
# exchange charges + stamp duty + GST — see execution/cost_model.py for the
# itemized version) as a single flat per-side fee, since vectorbt's fee
# model takes one rate rather than an itemized breakdown.
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0003


def build_price_panel(symbols: list[str] = WATCHLIST, period: str = "60d", interval: str = "5m") -> pd.DataFrame:
    """One column per symbol; symbols that fail to fetch are silently
    dropped (mirrors the committee's own tolerance for a missing/delisted
    watchlist entry)."""
    closes = {}
    for symbol in symbols:
        try:
            closes[symbol] = fetch_ohlcv(symbol, period=period, interval=interval)["Close"]
        except Exception:
            continue
    return pd.DataFrame(closes).dropna(how="all")


def run_sma_crossover_baseline(
    price_panel: pd.DataFrame,
    fast_window: int = FAST_WINDOW,
    slow_window: int = SLOW_WINDOW,
    init_cash: float = BUYING_POWER,
    freq: str = "15min",
) -> vbt.Portfolio:
    fast_ma = vbt.MA.run(price_panel, window=fast_window)
    slow_ma = vbt.MA.run(price_panel, window=slow_window)
    entries = fast_ma.ma_crossed_above(slow_ma)
    exits = fast_ma.ma_crossed_below(slow_ma)
    # vbt.MA.run() labels columns with a (window, ..., symbol) MultiIndex to
    # support parameter sweeps; with a single fixed window per side, that
    # collapses back to one column per input symbol in the same order —
    # relabel so callers can index by plain symbol name.
    entries.columns = price_panel.columns
    exits.columns = price_panel.columns

    return vbt.Portfolio.from_signals(
        price_panel,
        entries,
        exits,
        init_cash=init_cash,
        fees=FEE_RATE,
        slippage=SLIPPAGE_RATE,
        freq=freq,
    )
