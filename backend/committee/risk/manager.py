"""Risk Management Layer — README's final approval authority before any
capital is deployed. Consumes a ConsensusDecision, never produces one."""

from backend.committee.config import (
    EXPECTED_DRAWDOWN_VOL_MULTIPLIER,
    EXPECTED_RETURN_VOL_FRACTION,
    EXTREME_VOLATILITY_ANNUALIZED,
    HIGH_VOLATILITY_ANNUALIZED,
    MAX_POSITION_ALLOCATION,
    TRADING_DAYS_PER_YEAR,
    VOLATILITY_TRIM_FACTOR,
)
from backend.committee.market_data.context import MarketContext
from backend.committee.risk.volatility import estimate_annualized_volatility
from backend.committee.schemas import ConsensusDecision, Decision, RiskAction, RiskVerdict


def _expected_risk_return(consensus: ConsensusDecision, volatility: float) -> tuple[float, float]:
    """Heuristic Expected Return / Expected Drawdown (PS-mandated per-trade
    output) -- de-annualizes the GARCH volatility estimate to one session's
    expected move, then scales by confidence. Not a backtested figure; see
    config.EXPECTED_RETURN_VOL_FRACTION's docstring."""
    per_session_vol = volatility / (TRADING_DAYS_PER_YEAR**0.5)
    direction = {Decision.BUY: 1, Decision.SELL: -1}.get(consensus.decision, 0)
    expected_return = direction * consensus.confidence * EXPECTED_RETURN_VOL_FRACTION * per_session_vol
    expected_drawdown = EXPECTED_DRAWDOWN_VOL_MULTIPLIER * per_session_vol
    return expected_return, expected_drawdown


def evaluate(context: MarketContext, consensus: ConsensusDecision) -> RiskVerdict:
    volatility = estimate_annualized_volatility(context.ohlcv["Close"])
    expected_return, expected_drawdown = _expected_risk_return(consensus, volatility)

    if consensus.decision in (Decision.WAIT, Decision.HOLD):
        return RiskVerdict(
            action=RiskAction.APPROVE,
            approved_allocation=0.0,
            volatility_estimate=volatility,
            reason=f"Consensus is {consensus.decision.value} — no new capital requested, nothing to risk-check.",
            expected_return=expected_return,
            expected_drawdown=expected_drawdown,
        )

    if consensus.decision == Decision.SWITCH:
        # SWITCH always exits the current position -- reducing exposure is
        # never something the risk layer should block, even at extreme
        # volatility (refusing to let a position close would be the actively
        # dangerous outcome here, not the safe one).
        return RiskVerdict(
            action=RiskAction.APPROVE,
            approved_allocation=0.0,
            volatility_estimate=volatility,
            reason="Consensus is SWITCH — exiting to reallocate into a stronger candidate; exits are always approved.",
            expected_return=expected_return,
            expected_drawdown=expected_drawdown,
        )

    if volatility > EXTREME_VOLATILITY_ANNUALIZED:
        return RiskVerdict(
            action=RiskAction.REJECT,
            approved_allocation=0.0,
            volatility_estimate=volatility,
            reason=(
                f"Annualized volatility {volatility:.0%} exceeds the extreme-risk threshold "
                f"({EXTREME_VOLATILITY_ANNUALIZED:.0%}) — rejected for capital preservation."
            ),
            expected_return=expected_return,
            expected_drawdown=expected_drawdown,
        )

    allocation = min(consensus.allocation, MAX_POSITION_ALLOCATION)
    reduced = allocation < consensus.allocation

    if volatility > HIGH_VOLATILITY_ANNUALIZED:
        allocation *= VOLATILITY_TRIM_FACTOR
        reduced = True

    if reduced:
        return RiskVerdict(
            action=RiskAction.REDUCE,
            approved_allocation=allocation,
            volatility_estimate=volatility,
            reason=(
                f"Allocation trimmed from {consensus.allocation:.2f} to {allocation:.2f}: "
                f"position-limit cap ({MAX_POSITION_ALLOCATION:.2f}) and/or elevated volatility "
                f"({volatility:.0%} > {HIGH_VOLATILITY_ANNUALIZED:.0%})."
            ),
            expected_return=expected_return,
            expected_drawdown=expected_drawdown,
        )

    return RiskVerdict(
        action=RiskAction.APPROVE,
        approved_allocation=allocation,
        volatility_estimate=volatility,
        reason=f"Within position-limit and volatility ({volatility:.0%}) bounds — approved as proposed.",
        expected_return=expected_return,
        expected_drawdown=expected_drawdown,
    )
