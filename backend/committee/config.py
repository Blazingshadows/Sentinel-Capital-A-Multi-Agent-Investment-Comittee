"""Central settings and shared constants for the committee.

Loaded once from `.env` (see `.env.example`). Every layer imports constants
from here instead of hardcoding its own copy, so tuning a threshold or the
watchlist never requires touching more than one file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    newsapi_key: str = ""
    database_url: str = "sqlite:///./data/committee.db"


settings = Settings()

# --- Capital & leverage -----------------------------------------------------
CAPITAL = 10_000.0
LEVERAGE = 2
BUYING_POWER = CAPITAL * LEVERAGE

# --- Watchlist (liquid NSE large-caps; yfinance ticker = SYMBOL + ".NS") ----
WATCHLIST = [
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "INFY",
    "ICICIBANK",
    "SBIN",
    "TATAMOTORS",
    "ITC",
    "LT",
    "ADANIENT",
]

# --- Consensus Orchestrator (README "Dynamic Trust Framework") -------------
# Agent Influence = Confidence x Trust x Context Relevance
DECISION_THRESHOLD_WAIT = 0.15  # |weighted signal| below this -> WAIT
TRUST_PRIOR = 0.5  # Laplace-smoothed starting trust before any history
TRUST_SMOOTHING = 2.0  # Laplace smoothing constant (pseudo-observations)

# Static base expertise per agent for short-horizon intraday calls; multiplied
# by context_relevance (below) so "how good this agent generally is" and "how
# much this domain matters right now" stay independently tunable.
BASE_EXPERTISE = {
    "Technical": 1.2,
    "News & Sentiment": 1.0,
    "Macro": 0.8,
    "Contrarian": 0.6,
}

# Context multipliers applied to relevance on top of base expertise, keyed by
# a context flag the orchestration loop sets per cycle (e.g. "earnings_day").
CONTEXT_RELEVANCE_BOOST = {
    "earnings_day": {"News & Sentiment": 1.5, "Technical": 1.0, "Macro": 1.0, "Contrarian": 1.0},
    "rbi_policy_day": {"Macro": 1.8, "Technical": 1.0, "News & Sentiment": 1.0, "Contrarian": 1.0},
    "normal": {"Technical": 1.0, "News & Sentiment": 1.0, "Macro": 1.0, "Contrarian": 1.0},
}

# --- Risk Management Layer ---------------------------------------------------
MAX_POSITION_ALLOCATION = 1.0  # fraction of buying power in a single stock
HIGH_VOLATILITY_ANNUALIZED = 0.45  # GARCH-estimated annualized vol above this triggers a trim
VOLATILITY_TRIM_FACTOR = 0.5

# --- NSE intraday equity retail cost model (fractions, not percentages) ----
BROKERAGE_FLAT_CAP = 20.0
BROKERAGE_PCT = 0.0003
STT_PCT = 0.00025  # sell-side only
EXCHANGE_TXN_PCT = 0.0000297
SEBI_CHARGE_PER_CRORE = 10.0
STAMP_DUTY_PCT = 0.00003  # buy-side only
GST_PCT = 0.18  # on brokerage + exchange txn charges
SLIPPAGE_PCT_RANGE = (0.0002, 0.0005)

# --- Session timing (IST) ---------------------------------------------------
SESSION_START = "09:15"
SESSION_SQUARE_OFF = "15:15"
