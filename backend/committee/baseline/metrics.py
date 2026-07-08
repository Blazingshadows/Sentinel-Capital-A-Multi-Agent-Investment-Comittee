"""Standardized performance metrics via vectorbt's returns accessor. Applied
to *both* the baseline strategy's equity curve and the committee's own, so a
"we beat the baseline" claim rests on identical Sharpe/Sortino/max-drawdown/
win-rate methodology on both sides — not two different homegrown formulas
that happen to have the same names.
"""

import pandas as pd
import vectorbt  # noqa: F401  (import needed for its side effect: registers the .vbt pandas accessor)


def compute_returns_stats(portfolio_values: pd.Series, freq: str = "15min") -> pd.Series:
    returns = portfolio_values.pct_change().dropna()
    if len(returns) < 2:
        raise ValueError("Need at least 2 return observations to compute stats.")
    return returns.vbt.returns(freq=freq).stats()
