"""Fixed, versioned trading universes for Trend Following only."""

from __future__ import annotations

from finance_analysis.stocks.reference_data.stock_index import (
    CSI300_STOCK_INDEX,
    CSI500_STOCK_INDEX,
    SP500_STOCK_INDEX,
)
from finance_analysis.trend_following.models import UniverseMember


def normalize_market(market: str) -> str:
    normalized = str(market or "").strip().upper()
    if normalized not in {"CN", "US"}:
        raise ValueError("Trend Following market must be CN or US")
    return normalized


def get_universe(market: str) -> tuple[UniverseMember, ...]:
    normalized = normalize_market(market)
    if normalized == "US":
        source = {f"{code}.US": name for code, name in SP500_STOCK_INDEX.items()}
    else:
        source = {**CSI300_STOCK_INDEX, **CSI500_STOCK_INDEX}
    return tuple(UniverseMember(normalized, code, name) for code, name in sorted(source.items()))


def universe_by_code(market: str) -> dict[str, UniverseMember]:
    return {member.code: member for member in get_universe(market)}


__all__ = ["get_universe", "normalize_market", "universe_by_code"]
