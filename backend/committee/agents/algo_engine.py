"""AlgoEngine Agent — the systematic-signals research pipeline's live vote.

Loads the ensemble manifest trained offline by `scripts/train_algo_engine.py`
(many signal-subset x model-architecture candidates ranked by *backtested*
Sharpe, top-K fused by Sharpe-weighted averaging -- see
`backend/committee/algo_engine/`), computes each surviving member's required
signals for the current bar, and fuses their class probabilities into one
vote. A genuinely different point of view from both the LLM agents and
Forecasting's single hand-picked feature set: many candidate strategies
inspired by systematic trading styles (trend, mean-reversion, volatility,
volume, cross-sectional relative strength, tail-risk), selected by what
actually backtests well rather than hand-tuned weights.
"""

from pathlib import Path

from backend.committee.algo_engine.ensemble import EnsembleMember, fuse_probabilities, load_manifest
from backend.committee.algo_engine.features import build_all_signals
from backend.committee.algo_engine.models import FittedModel, load_model, predict_proba
from backend.committee.baseline.vectorbt_baseline import build_price_panel
from backend.committee.config import ALGO_ENSEMBLE_MANIFEST_PATH, WATCHLIST
from backend.committee.market_data.context import MarketContext
from backend.committee.schemas import AgentOutput, Decision

AGENT_NAME = "AlgoEngine"

_manifest_cache: list[EnsembleMember] | None = None
_manifest_load_attempted = False
_fitted_cache: dict[str, FittedModel] = {}
_panel_cache = None


def _load_manifest() -> list[EnsembleMember] | None:
    global _manifest_cache, _manifest_load_attempted
    if _manifest_load_attempted:
        return _manifest_cache
    _manifest_load_attempted = True

    manifest_path = Path(ALGO_ENSEMBLE_MANIFEST_PATH)
    if not manifest_path.exists():
        return None
    _manifest_cache = load_manifest(manifest_path)
    return _manifest_cache


def _get_fitted(member: EnsembleMember) -> FittedModel:
    if member.model_path not in _fitted_cache:
        _fitted_cache[member.model_path] = load_model(member.model_type, Path(member.model_path))
    return _fitted_cache[member.model_path]


def _get_panel():
    """Cross-sectional signals need the whole watchlist's close panel, not
    just this symbol's OHLCV. Built once per process and reused -- a
    snapshot as of process start, refreshed by restarting the service, the
    same lifetime as the loaded models themselves."""
    global _panel_cache
    if _panel_cache is None:
        _panel_cache = build_price_panel(WATCHLIST)
    return _panel_cache


def analyze(context: MarketContext) -> AgentOutput:
    members = _load_manifest()
    if not members:
        return AgentOutput(
            agent=AGENT_NAME,
            decision=Decision.WAIT,
            confidence=0.0,
            reasoning="No trained AlgoEngine ensemble found — run scripts/train_algo_engine.py first.",
            evidence=[],
        )

    panel = _get_panel()
    signals = build_all_signals(context.ohlcv, symbol=context.symbol, panel=panel)

    member_probs, weights, contributing = [], [], []
    for member in members:
        missing = [f for f in member.features if f not in signals.columns]
        if missing:
            continue
        latest = signals[list(member.features)].iloc[[-1]]
        if latest.isna().any(axis=None):
            continue
        fitted = _get_fitted(member)
        probs = predict_proba(fitted, latest)[0]
        member_probs.append(probs)
        weights.append(member.weight)
        contributing.append(member)

    if not member_probs:
        return AgentOutput(
            agent=AGENT_NAME,
            decision=Decision.WAIT,
            confidence=0.0,
            reasoning="Insufficient history to compute any AlgoEngine ensemble member's signals this cycle.",
            evidence=[],
        )

    fused = fuse_probabilities(member_probs, weights)
    confidence = float(fused.max())

    # Same margin-gated decision rule search.py backtested each member's
    # threshold against (see algo_engine.search._position_from_probs) --
    # applying plain argmax here instead would vote on razor-thin edges the
    # search never validated as worth trading.
    total_weight = sum(weights)
    agg_threshold = sum(w * m.threshold for w, m in zip(weights, contributing)) / total_weight if total_weight > 0 else 0.0
    bearish, neutral, bullish = fused[0], fused[1], fused[2]
    bullish_margin = bullish - max(bearish, neutral)
    bearish_margin = bearish - max(neutral, bullish)
    if bullish_margin > agg_threshold:
        decision = Decision.BUY
    elif bearish_margin > agg_threshold:
        decision = Decision.SELL
    else:
        decision = Decision.WAIT

    top_members = sorted(contributing, key=lambda m: m.weight, reverse=True)[:3]
    evidence = [
        f"{m.subset_name}/{m.config_name} (weight={m.weight:.2f}, backtest Sharpe={m.backtest_sharpe:.2f}, threshold={m.threshold:.2f})"
        for m in top_members
    ]

    return AgentOutput(
        agent=AGENT_NAME,
        decision=decision,
        confidence=round(confidence, 4),
        reasoning=(
            f"AlgoEngine ensemble ({len(contributing)}/{len(members)} members voted, "
            f"margin threshold={agg_threshold:.2f}): "
            f"P(bearish)={fused[0]:.2f}, P(neutral)={fused[1]:.2f}, P(bullish)={fused[2]:.2f}."
        ),
        evidence=evidence,
    )
