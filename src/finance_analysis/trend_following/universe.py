"""Database-backed Trend Following universe access."""

from finance_analysis.database.repositories.universe import UniverseResolver
from finance_analysis.trend_following.models import UniverseMember


def normalize_market(market: str) -> str:
    normalized = str(market or "").strip().upper()
    if normalized not in {"CN", "US"}:
        raise ValueError("Trend Following market must be CN or US")
    return normalized


def get_universe(market: str, resolver: UniverseResolver | None = None) -> tuple[UniverseMember, ...]:
    normalized = normalize_market(market)
    instruments = (resolver or UniverseResolver()).resolve_universe(f"{normalized.lower()}_trend")
    return tuple(UniverseMember(normalized, item.code, item.name) for item in instruments)


def universe_by_code(market: str, resolver: UniverseResolver | None = None) -> dict[str, UniverseMember]:
    return {member.code: member for member in get_universe(market, resolver)}


__all__ = ["get_universe", "normalize_market", "universe_by_code"]
