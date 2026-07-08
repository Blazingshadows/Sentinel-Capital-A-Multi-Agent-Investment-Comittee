"""Cross-sectional relative-strength signals -- a quality/rotation proxy in
the spirit of "own the strongest names, avoid the weakest," adapted from
Buffett-style relative-quality screening since Breeze has no fundamentals
feed to screen on directly. Needs the whole watchlist's close panel, not
just one symbol's OHLCV, so these take `symbol`/`panel` kwargs unlike every
other signal module -- see `algo_engine.features.build_all_signals`, which
is the only caller that supplies them.
"""

import pandas as pd


def relative_strength(ohlcv: pd.DataFrame, symbol: str, panel: pd.DataFrame, window: int = 20) -> pd.Series:
    """This symbol's `window`-bar return minus the peer median return over
    the same window -- positive means outperforming the watchlist, not just
    rising in absolute terms."""
    if panel is None or panel.empty or symbol not in panel.columns:
        return pd.Series(float("nan"), index=ohlcv.index)

    panel_returns = panel.pct_change(periods=window)
    own_return = panel_returns[symbol]
    peer_return = panel_returns.drop(columns=[symbol]).median(axis=1)
    relative = (own_return - peer_return).reindex(ohlcv.index)
    return relative.ffill()


def sector_momentum_rank(ohlcv: pd.DataFrame, symbol: str, panel: pd.DataFrame, window: int = 20) -> pd.Series:
    """This symbol's percentile rank (0-1) of `window`-bar return within the
    watchlist -- a coarse-grained rotation signal (top of the pack vs.
    bottom), robust to any single peer's move dominating a median."""
    if panel is None or panel.empty or symbol not in panel.columns:
        return pd.Series(float("nan"), index=ohlcv.index)

    panel_returns = panel.pct_change(periods=window)
    ranks = panel_returns.rank(axis=1, pct=True)[symbol].reindex(ohlcv.index)
    return ranks.ffill()
