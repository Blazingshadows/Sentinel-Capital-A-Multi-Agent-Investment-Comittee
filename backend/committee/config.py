"""Central settings and shared constants for the committee.

Loaded once from `.env` (see `.env.example`). Every layer imports constants
from here instead of hardcoding its own copy, so tuning a threshold or the
watchlist never requires touching more than one file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    newsapi_key: str = ""
    database_url: str = "sqlite:///./data/committee.db"

    # ICICI Direct Breeze API. api_secret is a static app credential; the
    # session token is an api_session value SEBI requires the user to grab
    # via a manual browser login every trading day (expires at midnight) --
    # there's no automated way around that, so this must be refreshed daily.
    breeze_api_key: str = ""
    breeze_api_secret: str = ""
    breeze_session_token: str = ""


settings = Settings()

# --- Capital & leverage -----------------------------------------------------
CAPITAL = 10_000.0
LEVERAGE = 2
BUYING_POWER = CAPITAL * LEVERAGE

# --- Watchlist (liquid NSE large-caps) --------------------------------------
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

# Breeze's own stock_code, which is NOT the NSE tradingsymbol (e.g. RELIANCE's
# code is "RELIND"). Verified 2026-07-09 against a live account by fetching
# each symbol via breeze_client and cross-checking INFY through get_names().
BREEZE_STOCK_CODE_MAP = {
    "RELIANCE": "RELIND",
    "TCS": "TCS",
    "HDFCBANK": "HDFBAN",
    "INFY": "INFTEC",
    "ICICIBANK": "ICIBAN",
    "SBIN": "STABAN",
    "TATAMOTORS": "TATMOT",
    "ITC": "ITC",
    "LT": "LARTOU",
    "ADANIENT": "ADAENT",
}

# Breeze has no fundamentals/sector data (it's a trading API, not a data
# vendor) -- static lookup for the fixed watchlist replaces yfinance's
# `.info` for the two fields the Macro agent actually reads. marketCap
# figures are rough approximations (mid-2020s levels), not live values --
# fine for a soft LLM prompt hint, but refresh periodically if precision matters.
WATCHLIST_FUNDAMENTALS = {
    "RELIANCE": {"sector": "Energy", "marketCap": 19_500_000_000_000},
    "TCS": {"sector": "Information Technology", "marketCap": 13_500_000_000_000},
    "HDFCBANK": {"sector": "Financial Services", "marketCap": 12_500_000_000_000},
    "INFY": {"sector": "Information Technology", "marketCap": 6_200_000_000_000},
    "ICICIBANK": {"sector": "Financial Services", "marketCap": 8_500_000_000_000},
    "SBIN": {"sector": "Financial Services", "marketCap": 7_000_000_000_000},
    "TATAMOTORS": {"sector": "Automobile", "marketCap": 3_400_000_000_000},
    "ITC": {"sector": "Fast Moving Consumer Goods", "marketCap": 5_500_000_000_000},
    "LT": {"sector": "Construction", "marketCap": 4_800_000_000_000},
    "ADANIENT": {"sector": "Diversified", "marketCap": 2_700_000_000_000},
}

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
    "Forecasting": 1.0,
    "AlgoEngine": 1.0,
}

# Context multipliers applied to relevance on top of base expertise, keyed by
# a context flag the orchestration loop sets per cycle (e.g. "earnings_day").
CONTEXT_RELEVANCE_BOOST = {
    "earnings_day": {"News & Sentiment": 1.5, "Technical": 1.0, "Macro": 1.0, "Contrarian": 1.0, "Forecasting": 1.0, "AlgoEngine": 1.0},
    "rbi_policy_day": {"Macro": 1.8, "Technical": 1.0, "News & Sentiment": 1.0, "Contrarian": 1.0, "Forecasting": 1.0, "AlgoEngine": 1.0},
    "normal": {"Technical": 1.0, "News & Sentiment": 1.0, "Macro": 1.0, "Contrarian": 1.0, "Forecasting": 1.0, "AlgoEngine": 1.0},
}

# --- Debate Layer ------------------------------------------------------------
# Max fraction by which the Contrarian's disagreement can damp another
# agent's confidence during the revision pass (README step 4). Scaled by the
# Contrarian's own confidence, so a low-confidence dissent barely moves
# anything while a highly-confident one can roughly halve it.
REVISION_DAMPING_FACTOR = 0.5

# --- Risk Management Layer ---------------------------------------------------
MAX_POSITION_ALLOCATION = 1.0  # fraction of buying power in a single stock
HIGH_VOLATILITY_ANNUALIZED = 0.45  # GARCH-estimated annualized vol above this triggers a trim
EXTREME_VOLATILITY_ANNUALIZED = 1.0  # above this, reject the trade outright
VOLATILITY_TRIM_FACTOR = 0.5
INTRADAY_BARS_PER_DAY = 75  # NSE 9:15-15:30 session / 5-min bars
TRADING_DAYS_PER_YEAR = 252

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

# --- LLM provider diversity ---------------------------------------------------
# Different providers for different agents on purpose: an LLM agent's
# reasoning is shaped by its training, not just its prompt, so routing each
# LLM-backed agent through a different lab's model gives the Debate Layer
# genuinely independent points of view instead of one model role-playing
# three personas. Contrarian (the devil's-advocate role) gets the provider
# most likely to disagree for reasons the others wouldn't.
AGENT_PROVIDER_MAP = {
    "News & Sentiment": "gemini",
    "Macro": "openai",
    "Contrarian": "anthropic",
}
GEMINI_MODEL_NAME = "gemini-1.5-flash"
OPENAI_MODEL_NAME = "gpt-5-mini"
ANTHROPIC_MODEL_NAME = "claude-haiku-4-5"

# --- Forecasting Agent (LightGBM, not an LLM call) --------------------------
# A genuinely different point of view from the LLM agents: pattern-matching on
# raw price/volume history rather than language-based reasoning over evidence.
FORECAST_MODEL_PATH = "data/models/forecasting_lgbm.txt"
FORECAST_META_PATH = "data/models/forecasting_meta.json"
FORECAST_LAG_PERIODS = [1, 2, 3, 5, 10]
FORECAST_VOLATILITY_WINDOW = 10
FORECAST_LOOKAHEAD_BARS = 9  # bars ahead the label/prediction targets -- 9x5m = ~45min horizon (was 3x15m under yfinance)
# Deadzone scales with each stock's own rolling volatility rather than a fixed
# return -- a flat threshold mislabels a calm stock's noise as a real move and
# a volatile stock's real moves as noise when pooled together for training.
FORECAST_DEADZONE_VOL_MULTIPLIER = 0.5
FORECAST_DEADZONE_MIN_RETURN = 0.0005  # floor so a near-zero rolling vol can't collapse the deadzone to ~0
FORECAST_TRAIN_PERIOD = "180d"  # Breeze has no 60d cap (yfinance did); can grow toward its ~3yr retention later
FORECAST_TRAIN_INTERVAL = "5m"  # Breeze's get_historical_data_v2 has no native 15m bucket
FORECAST_MIN_TRAINING_ROWS = 500

# --- AlgoEngine (signal-library search + backtest-ranked model ensemble) ---
# A systematic-signals research pipeline distinct from Forecasting's single
# hand-picked feature set: searches many (signal-subset x model architecture)
# candidates, ranks them by backtested Sharpe (not accuracy), and fuses the
# survivors into one ensemble. See backend/committee/signals/ and
# backend/committee/algo_engine/.
ALGO_MODEL_DIR = "data/models/algo_engine"
ALGO_ENSEMBLE_MANIFEST_PATH = "data/models/algo_engine/ensemble.json"
ALGO_TRAIN_PERIOD = FORECAST_TRAIN_PERIOD
ALGO_TRAIN_INTERVAL = FORECAST_TRAIN_INTERVAL
ALGO_MIN_TRAINING_ROWS = FORECAST_MIN_TRAINING_ROWS
ALGO_RANDOM_SUBSET_COUNT = 15  # random signal-subset candidates on top of the one-per-style + all-combined subsets
ALGO_RANDOM_SUBSET_FRACTION = 0.5  # fraction of all signals sampled into each random subset
ALGO_WALK_FORWARD_FOLDS = 4  # expanding-window folds per symbol, pooled across WATCHLIST
ALGO_TOP_K = 5  # number of top-by-Sharpe candidates fused into the final ensemble
ALGO_SEED = 42
ALGO_BACKTEST_FREQ = "5min"  # matches ALGO_TRAIN_INTERVAL, passed to vectorbt/compute_returns_stats

# Three hyperparameter presets per architecture (conservative/default/
# aggressive), varying capacity (num_leaves/max_depth/...) *and* explicit
# regularization (L1/L2, gamma, ccp_alpha) together -- the pooled per-fold
# training set is small (a few thousand rows in early folds) and the label
# is a noisy volatility-scaled 3-way call, exactly the regime where
# unpenalized boosting overfits fastest and reproduces the flip-flopping/
# cost-drag problem the first (single-preset, unregularized) search run
# showed. `algo_engine.models.build_model_configs` flattens this into the
# list of ModelConfig candidates the search actually trains.
ALGO_MODEL_PRESETS = {
    "lightgbm": {
        "conservative": {"num_leaves": 7, "min_data_in_leaf": 60, "learning_rate": 0.05, "lambda_l2": 5.0},
        "default": {"num_leaves": 15, "min_data_in_leaf": 20, "learning_rate": 0.05, "lambda_l2": 0.0},
        "aggressive": {"num_leaves": 31, "min_data_in_leaf": 10, "learning_rate": 0.1, "lambda_l2": 0.0},
    },
    "xgboost": {
        "conservative": {"max_depth": 3, "min_child_weight": 10, "subsample": 0.7, "colsample_bytree": 0.7, "reg_lambda": 5.0, "gamma": 1.0, "learning_rate": 0.05},
        "default": {"max_depth": 4, "min_child_weight": 1, "subsample": 1.0, "colsample_bytree": 1.0, "reg_lambda": 1.0, "gamma": 0.0, "learning_rate": 0.05},
        "aggressive": {"max_depth": 6, "min_child_weight": 1, "subsample": 1.0, "colsample_bytree": 1.0, "reg_lambda": 0.0, "gamma": 0.0, "learning_rate": 0.1},
    },
    "random_forest": {
        "conservative": {"max_depth": 4, "min_samples_leaf": 50, "n_estimators": 200, "ccp_alpha": 0.01},
        "default": {"max_depth": 6, "min_samples_leaf": 20, "n_estimators": 200, "ccp_alpha": 0.0},
        "aggressive": {"max_depth": 10, "min_samples_leaf": 10, "n_estimators": 500, "ccp_alpha": 0.0},
    },
}

# Backtested post-hoc on each already-trained candidate's saved probabilities
# (no retraining) -- 0.0 reproduces the old plain-argmax behavior; the
# others require the winning class to beat the runner-up by a real margin
# before entering a position, directly targeting the flip-flopping/
# transaction-cost drag a razor-thin argmax call produces at 5-minute bars.
ALGO_CONFIDENCE_THRESHOLDS = [0.0, 0.05, 0.10, 0.15]

# Tail of each fold's training pool held out for LightGBM/XGBoost early
# stopping, so the boosting-round count is chosen automatically per
# (fold, config) instead of a fixed guess.
ALGO_VALIDATION_FRACTION = 0.15
ALGO_EARLY_STOPPING_ROUNDS = 20
ALGO_MAX_BOOST_ROUNDS = 500
