"""Technical Analyst Agent — README's first specialist. Pure pandas/numpy
math over OHLCV, no LLM call: RSI, MACD, EMA cross, and short-horizon
momentum, fused into a directional call with a self-consistent confidence."""

import pandas as pd

from backend.committee.market_data.context import MarketContext
from backend.committee.schemas import AgentOutput, Decision

AGENT_NAME = "Technical"

# Component weights sum to 1.0 at full agreement, so `score` naturally lands
# in [-1, 1] and doubles as the confidence magnitude.
WEIGHT_RSI = 0.3
WEIGHT_EMA_CROSS = 0.3
WEIGHT_MACD = 0.2
WEIGHT_MOMENTUM = 0.2
MOMENTUM_LOOKBACK = 10
WAIT_BAND = 0.15  # |score| within this band -> not enough edge to act


def compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def compute_ema(closes: pd.Series, period: int) -> pd.Series:
    return closes.ewm(span=period, adjust=False).mean()


def compute_macd(closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = compute_ema(closes, fast) - compute_ema(closes, slow)
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_momentum(closes: pd.Series, period: int = MOMENTUM_LOOKBACK) -> pd.Series:
    return closes.pct_change(periods=period)


def analyze(context: MarketContext) -> AgentOutput:
    closes = context.ohlcv["Close"]

    if len(closes) < 50:
        return AgentOutput(
            agent=AGENT_NAME,
            decision=Decision.WAIT,
            confidence=0.0,
            reasoning="Insufficient OHLCV history for a reliable technical read (<50 bars).",
            evidence=[],
        )

    rsi = compute_rsi(closes).iloc[-1]
    ema_fast = compute_ema(closes, 20).iloc[-1]
    ema_slow = compute_ema(closes, 50).iloc[-1]
    _, _, macd_hist = compute_macd(closes)
    macd_hist_last = macd_hist.iloc[-1]
    momentum = compute_momentum(closes).iloc[-1]

    score = 0.0
    evidence = []

    if rsi < 30:
        score += WEIGHT_RSI
        evidence.append(f"RSI={rsi:.1f} (oversold)")
    elif rsi > 70:
        score -= WEIGHT_RSI
        evidence.append(f"RSI={rsi:.1f} (overbought)")
    else:
        evidence.append(f"RSI={rsi:.1f} (neutral)")

    if ema_fast > ema_slow:
        score += WEIGHT_EMA_CROSS
        evidence.append(f"EMA20={ema_fast:.2f} > EMA50={ema_slow:.2f} (bullish cross)")
    else:
        score -= WEIGHT_EMA_CROSS
        evidence.append(f"EMA20={ema_fast:.2f} < EMA50={ema_slow:.2f} (bearish cross)")

    if macd_hist_last > 0:
        score += WEIGHT_MACD
        evidence.append(f"MACD histogram={macd_hist_last:.3f} (positive)")
    else:
        score -= WEIGHT_MACD
        evidence.append(f"MACD histogram={macd_hist_last:.3f} (negative)")

    momentum_component = max(-WEIGHT_MOMENTUM, min(WEIGHT_MOMENTUM, momentum * 4))
    score += momentum_component
    evidence.append(f"momentum={momentum * 100:.2f}% over last {MOMENTUM_LOOKBACK} bars")

    score = max(-1.0, min(1.0, score))

    if score > WAIT_BAND:
        decision = Decision.BUY
    elif score < -WAIT_BAND:
        decision = Decision.SELL
    else:
        decision = Decision.WAIT

    return AgentOutput(
        agent=AGENT_NAME,
        decision=decision,
        confidence=round(abs(score), 2),
        reasoning="; ".join(evidence),
        evidence=evidence,
    )
