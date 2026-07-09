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

# --- Watchlist ----------------------------------------------------------------
# Nifty 50 large-caps (original 10) + Nifty Midcap 100 (below) -- intraday
# moves aren't confined to large-caps, so the universe was widened to include
# the full official Midcap 100 index for more setups per cycle.
NIFTY_LARGECAP_WATCHLIST = [
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

# NSE Nifty Midcap 100 official constituent list (fetched from
# archives.nseindia.com 2026-07-09). Rebalanced twice a year by NSE Indices --
# re-pull and diff periodically so delisted/promoted names don't go stale.
NIFTY_MIDCAP100_WATCHLIST = [
    "360ONE", "APLAPOLLO", "AUBANK", "ATGL", "ABCAPITAL", "ALKEM", "ASHOKLEY",
    "ASTRAL", "AUROPHARMA", "BSE", "BANKINDIA", "BDL", "BHARATFORG", "BHEL",
    "GROWW", "BIOCON", "BLUESTARCO", "COCHINSHIP", "COFORGE", "COLPAL",
    "CONCOR", "COROMANDEL", "DABUR", "DIXON", "EXIDEIND", "NYKAA",
    "FEDERALBNK", "FORTIS", "GVT&D", "GMRAIRPORT", "GLENMARK", "GODFRYPHLP",
    "GODREJPROP", "HAVELLS", "HEROMOTOCO", "HINDPETRO", "POWERINDIA", "HUDCO",
    "ICICIGI", "ICICIAMC", "IDFCFIRSTB", "INDIANB", "IRCTC", "IREDA",
    "INDUSTOWER", "INDUSINDBK", "NAUKRI", "JSWENERGY", "JUBLFOOD", "KEI",
    "KPITTECH", "KALYANKJIL", "LTF", "LGEINDIA", "LICHSGFIN", "LAURUSLABS",
    "LENSKART", "LUPIN", "MRF", "M&MFIN", "MANKIND", "MARICO", "MFSL",
    "MOTILALOFS", "MPHASIS", "MCX", "NHPC", "NMDC", "NATIONALUM",
    "OBEROIRLTY", "OIL", "PAYTM", "OFSS", "POLICYBZR", "PIIND", "PAGEIND",
    "PATANJALI", "PERSISTENT", "PHOENIXLTD", "POLYCAB", "PREMIERENE",
    "PRESTIGE", "RADICO", "RVNL", "SBICARD", "SRF", "SAIL", "SUPREMEIND",
    "SUZLON", "SWIGGY", "TATACOMM", "TATAELXSI", "TATAINVEST", "TIINDIA",
    "UPL", "VMM", "IDEA", "VOLTAS", "WAAREEENER", "YESBANK",
]

WATCHLIST = NIFTY_LARGECAP_WATCHLIST + NIFTY_MIDCAP100_WATCHLIST

# Breeze's own stock_code, which is NOT the NSE tradingsymbol (e.g. RELIANCE's
# code is "RELIND"). Verified 2026-07-09 against a live account by fetching
# each symbol via breeze_client and cross-checking INFY through get_names().
# The Midcap 100 block below was resolved the same way, in bulk, via
# get_names() for every symbol in NIFTY_MIDCAP100_WATCHLIST.
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
    "360ONE": "IIFWEA",
    "APLAPOLLO": "APLAPO",
    "AUBANK": "AUSMA",
    "ATGL": "ADAGAS",
    "ABCAPITAL": "ADICAP",
    "ALKEM": "ALKLAB",
    "ASHOKLEY": "ASHLEY",
    "ASTRAL": "ASTPOL",
    "AUROPHARMA": "AURPHA",
    "BSE": "BSE",
    "BANKINDIA": "BANIND",
    "BDL": "BHADYN",
    "BHARATFORG": "BHAFOR",
    "BHEL": "BHEL",
    "GROWW": "BILGAR",
    "BIOCON": "BIOCON",
    "BLUESTARCO": "BLUSTA",
    "COCHINSHIP": "COCSHI",
    "COFORGE": "NIITEC",
    "COLPAL": "COLPAL",
    "CONCOR": "CONCOR",
    "COROMANDEL": "CORINT",
    "DABUR": "DABIND",
    "DIXON": "DIXTEC",
    "EXIDEIND": "EXIIND",
    "NYKAA": "FSNECO",
    "FEDERALBNK": "FEDBAN",
    "FORTIS": "FORHEA",
    "GVT&D": "ALSTD",
    "GMRAIRPORT": "GMRINF",
    "GLENMARK": "GLEPHA",
    "GODFRYPHLP": "GODPHI",
    "GODREJPROP": "GODPRO",
    "HAVELLS": "HAVIND",
    "HEROMOTOCO": "HERHON",
    "HINDPETRO": "HINPET",
    "POWERINDIA": "ABBPOW",
    "HUDCO": "HUDCO",
    "ICICIGI": "ICILOM",
    "ICICIAMC": "ICIAMC",
    "IDFCFIRSTB": "IDFBAN",
    "INDIANB": "INDIBA",
    "IRCTC": "INDRAI",
    "IREDA": "INDREN",
    "INDUSTOWER": "BHAINF",
    "INDUSINDBK": "INDBA",
    "NAUKRI": "INFEDG",
    "JSWENERGY": "JSWENE",
    "JUBLFOOD": "JUBFOO",
    "KEI": "KEIIND",
    "KPITTECH": "KPITE",
    "KALYANKJIL": "KALJEW",
    "LTF": "LTFINA",
    "LGEINDIA": "LGELEC",
    "LICHSGFIN": "LICHF",
    "LAURUSLABS": "LAULAB",
    "LENSKART": "LENSOL",
    "LUPIN": "LUPIN",
    "MRF": "MRFTYR",
    "M&MFIN": "MAHFIN",
    "MANKIND": "MAPHA",
    "MARICO": "MARLIM",
    "MFSL": "MAXFIN",
    "MOTILALOFS": "MOTOSW",
    "MPHASIS": "MPHLIM",
    "MCX": "MCX",
    "NHPC": "NHPC",
    "NMDC": "NATMIN",
    "NATIONALUM": "NATALU",
    "OBEROIRLTY": "OBEREA",
    "OIL": "OILIND",
    "PAYTM": "ONE97",
    "OFSS": "ORAFIN",
    "POLICYBZR": "PBFINT",
    "PIIND": "PIIND",
    "PAGEIND": "PAGIND",
    "PATANJALI": "RUCSOY",
    "PERSISTENT": "PERSYS",
    "PHOENIXLTD": "PHOMIL",
    "POLYCAB": "POLI",
    "PREMIERENE": "PREENR",
    "PRESTIGE": "PREEST",
    "RADICO": "RADKHA",
    "RVNL": "RAIVIK",
    "SBICARD": "SBICAR",
    "SRF": "SRF",
    "SAIL": "SAIL",
    "SUPREMEIND": "SUPIND",
    "SUZLON": "SUZENE",
    "SWIGGY": "SWILIM",
    "TATACOMM": "TATCOM",
    "TATAELXSI": "TATELX",
    "TATAINVEST": "TATINV",
    "TIINDIA": "TUBIN",
    "UPL": "UNIP",
    "VMM": "VISMEG",
    "IDEA": "IDECEL",
    "VOLTAS": "VOLTAS",
    "WAAREEENER": "WAAENE",
    "YESBANK": "YESBAN",
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
}

# Context multipliers applied to relevance on top of base expertise, keyed by
# a context flag the orchestration loop sets per cycle (e.g. "earnings_day").
CONTEXT_RELEVANCE_BOOST = {
    "earnings_day": {"News & Sentiment": 1.5, "Technical": 1.0, "Macro": 1.0, "Contrarian": 1.0, "Forecasting": 1.0},
    "rbi_policy_day": {"Macro": 1.8, "Technical": 1.0, "News & Sentiment": 1.0, "Contrarian": 1.0, "Forecasting": 1.0},
    "normal": {"Technical": 1.0, "News & Sentiment": 1.0, "Macro": 1.0, "Contrarian": 1.0, "Forecasting": 1.0},
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
GEMINI_MODEL_NAME = "gemini-2.5-flash"
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
