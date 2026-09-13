"""Use the system-owned daily-sync universe, selecting only its active stocks."""

from finance_analysis.database.repositories.universe import UniverseResolver


def universe_key(market: str) -> str:
    if market not in {"CN", "US"}:
        raise ValueError("market must be CN or US")
    return f"{market.lower()}_daily_sync"


def get_universe_codes(market: str, resolver: UniverseResolver | None = None) -> set[str]:
    return {
        item.code
        for item in (resolver or UniverseResolver()).resolve_universe(universe_key(market))
        if item.market == market and item.instrument_type == "STOCK" and item.listing_status == "ACTIVE"
    }
