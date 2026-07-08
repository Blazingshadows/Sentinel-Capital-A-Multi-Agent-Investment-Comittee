"""Cross-symbol capital allocator — the piece of "Portfolio diversification /
Exposure Control" the Risk Management Layer can't cover on its own: each
symbol's risk verdict is computed independently, with no visibility into
what capital *other* watchlist symbols want the same cycle. Without this,
every symbol sizes its trade against the full BUYING_POWER as if it had a
private pool, and several simultaneously-strong signals across the
watchlist can jointly request far more capital than the portfolio actually
has (verified: three simultaneous BUY signals at the per-symbol cap
requested 291% of buying power and drove cash to -Rs 38,000).

Confidence-weighted: symbols wanting *more* exposure than they already hold
compete for whatever capital headroom remains, proportional to their
Directional Confidence Score — stronger convictions get a larger share of
the available budget, weaker ones get scaled down rather than shut out
entirely. Trades that *reduce* exposure (or flip at no larger a magnitude)
are never throttled, since they free capital rather than consume it.
"""

from dataclasses import dataclass

from backend.committee.config import BUYING_POWER
from backend.committee.execution.portfolio import Portfolio
from backend.committee.schemas import ConsensusDecision, Decision, RiskAction, RiskVerdict


@dataclass
class AllocationCandidate:
    symbol: str
    price: float
    consensus: ConsensusDecision
    risk_verdict: RiskVerdict


def _is_active(candidate: AllocationCandidate) -> bool:
    return (
        candidate.consensus.decision != Decision.WAIT
        and candidate.risk_verdict.action != RiskAction.REJECT
        and candidate.risk_verdict.approved_allocation > 0
    )


def allocate_capital(candidates: list[AllocationCandidate], portfolio: Portfolio) -> dict[str, RiskVerdict]:
    """Returns a risk verdict per symbol, each identical to the input unless
    the symbol's requested *increase* in gross exposure had to be scaled
    down to fit the portfolio's remaining capital headroom this cycle."""
    price_by_symbol = {c.symbol: c.price for c in candidates}
    current_gross_exposure = sum(
        abs(qty * price_by_symbol.get(symbol, 0.0)) for symbol, qty in portfolio.positions.items()
    )
    available_headroom = max(0.0, BUYING_POWER - current_gross_exposure)

    incremental_needs: dict[str, float] = {}
    for candidate in candidates:
        if not _is_active(candidate):
            continue
        current_qty = portfolio.positions.get(candidate.symbol, 0.0)
        current_gross = abs(current_qty * candidate.price)
        requested_gross = candidate.risk_verdict.approved_allocation * BUYING_POWER
        incremental = requested_gross - current_gross
        if incremental > 0:
            incremental_needs[candidate.symbol] = incremental

    adjusted: dict[str, RiskVerdict] = {c.symbol: c.risk_verdict for c in candidates}
    total_incremental_needed = sum(incremental_needs.values())
    if total_incremental_needed <= available_headroom:
        return adjusted  # enough headroom for everyone; no scaling needed

    confidence_by_symbol = {c.symbol: c.consensus.confidence for c in candidates}
    total_confidence = sum(confidence_by_symbol[s] for s in incremental_needs) or 1.0

    for candidate in candidates:
        symbol = candidate.symbol
        if symbol not in incremental_needs:
            continue

        share = confidence_by_symbol[symbol] / total_confidence
        allocated_incremental = available_headroom * share
        current_qty = portfolio.positions.get(symbol, 0.0)
        current_gross = abs(current_qty * candidate.price)
        final_allocation = (current_gross + allocated_incremental) / BUYING_POWER

        original = candidate.risk_verdict
        adjusted[symbol] = RiskVerdict(
            action=RiskAction.REDUCE,
            approved_allocation=final_allocation,
            volatility_estimate=original.volatility_estimate,
            reason=(
                f"{original.reason} | capital-constrained across the watchlist: scaled to "
                f"{final_allocation:.2f}x buying power ({share:.0%} confidence-weighted share "
                f"of Rs {available_headroom:,.0f} available headroom)"
            ),
        )

    return adjusted
