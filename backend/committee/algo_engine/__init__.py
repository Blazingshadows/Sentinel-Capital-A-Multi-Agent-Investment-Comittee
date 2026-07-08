"""AlgoEngine: signal-library search + backtest-ranked model ensemble.

Distinct from `agents/forecasting.py`'s single hand-picked LightGBM feature
set -- this searches many (signal-subset x model-architecture) candidates
(`search.py`), ranks them by backtested Sharpe rather than accuracy
(`search.py` again, via `baseline/metrics.py`), and fuses the survivors into
one weighted ensemble (`ensemble.py`). `features.py` builds the signal
matrix and the candidate feature subsets from `backend.committee.signals`.
"""
