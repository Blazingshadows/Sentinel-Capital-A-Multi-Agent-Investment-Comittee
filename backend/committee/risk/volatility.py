"""GARCH(1,1) volatility estimation — the quantitative core of the Risk
Management Layer's "volatility checks" responsibility."""

import numpy as np
import pandas as pd
from arch import arch_model

from backend.committee.config import INTRADAY_BARS_PER_DAY, TRADING_DAYS_PER_YEAR


def estimate_annualized_volatility(
    closes: pd.Series,
    bars_per_day: int = INTRADAY_BARS_PER_DAY,
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Fits a GARCH(1,1) on percentage returns and annualizes the one-step-
    ahead forecast volatility. Falls back to plain historical std when there
    isn't enough history for GARCH to converge (needs ~50+ points) — a
    coarser but still usable estimate rather than aborting the risk check.
    """
    returns = closes.pct_change().dropna() * 100  # arch_model prefers % scale

    periods_per_year = bars_per_day * trading_days_per_year

    if len(returns) < 50:
        return float(returns.std() / 100 * np.sqrt(periods_per_year)) if len(returns) > 1 else 0.0

    try:
        model = arch_model(returns, vol="Garch", p=1, q=1, dist="normal", rescale=False)
        result = model.fit(disp="off")
        forecast = result.forecast(horizon=1, reindex=False)
        next_variance_pct = forecast.variance.values[-1, 0]
        daily_vol = np.sqrt(next_variance_pct) / 100
        return float(daily_vol * np.sqrt(periods_per_year))
    except Exception:
        return float(returns.std() / 100 * np.sqrt(periods_per_year))
