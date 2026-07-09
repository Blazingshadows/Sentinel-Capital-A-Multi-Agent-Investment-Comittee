"""Session-start watchlist selection: runs Opportunity Discovery over the
live-fetchable NSE universe and hands the committee its top
`COMMITTEE_WATCHLIST_SIZE` candidates by opportunity_score, instead of
always trading the same fixed 10 symbols. Discovery itself never emits a
directional call -- it only narrows the search space (see
discovery/agent.py); this is the one place that search space actually
becomes what gets traded.

Runs once per session (live or replay), not once per cycle: Discovery's
own data fetch alone touches every symbol in the universe, so re-running it
every 5-minute cycle would multiply an already non-trivial one-time cost by
however many cycles a session runs.
"""

import logging

from backend.committee.config import COMMITTEE_WATCHLIST_SIZE, WATCHLIST

logger = logging.getLogger(__name__)


def select_session_watchlist(progress: dict | None = None) -> list[str]:
    """Returns up to COMMITTEE_WATCHLIST_SIZE symbols, rank-ordered by
    Discovery's opportunity_score. Falls back to the fixed WATCHLIST if
    Discovery can't produce a usable result -- a session should always have
    something to trade, never nothing.

    `progress`, if given, is mutated in place with the same keys
    `api.main`'s /session/progress endpoint reads directly (see that
    endpoint's docstring for the full shape) -- the API layer just needs to
    hold a reference to the same dict.
    """
    if progress is not None:
        progress["phase"] = "discovering"
        progress["detail"] = "Loading NSE universe..."

    try:
        from backend.committee.discovery.registry import build_default_discovery_agent

        agent = build_default_discovery_agent()
        result = agent.discover()
    except Exception:
        logger.exception("Opportunity Discovery failed -- falling back to the fixed watchlist.")
        if progress is not None:
            progress["detail"] = f"Discovery unavailable, using fixed watchlist ({len(WATCHLIST)} symbols)."
        return list(WATCHLIST)

    selected = [c.symbol for c in result.candidates[:COMMITTEE_WATCHLIST_SIZE]]
    if not selected:
        logger.warning("Discovery returned no candidates -- falling back to the fixed watchlist.")
        if progress is not None:
            progress["detail"] = f"Discovery found nothing tradeable, using fixed watchlist ({len(WATCHLIST)} symbols)."
        return list(WATCHLIST)

    if progress is not None:
        progress["universe_size"] = result.universe_size
        progress["scanned"] = result.scanned
        progress["survived_scan"] = result.survived_scan
        progress["selected_count"] = result.selected_count
        progress["watchlist"] = selected
        progress["detail"] = (
            f"{result.universe_size} loaded -> {result.survived_scan} passed screen -> "
            f"{result.selected_count} scored & diversified -> trading top {len(selected)}"
        )

    logger.info(
        "Discovery-driven watchlist: %d universe -> %d survived -> %d selected -> trading top %d.",
        result.universe_size, result.survived_scan, result.selected_count, len(selected),
    )
    return selected
