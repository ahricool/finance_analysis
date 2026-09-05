"""Database-backed ETF Rotation universe access."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from finance_analysis.database.repositories.universe import UniverseRepository


@dataclass(frozen=True)
class ETFUniverseMember:
    code: str
    name: str
    category: str
    theme: str
    risk_group: str
    enabled: bool = True
    market: str = "CN"

    def to_dict(self) -> dict[str, str | bool]:
        return asdict(self)


def normalize_etf_market(market: str = "CN") -> str:
    normalized = str(market or "").strip().upper()
    if normalized not in {"CN", "US"}:
        raise ValueError(f"Unsupported ETF Rotation market={market!r}; expected CN or US")
    return normalized


def get_etf_universe(
    market: str = "CN",
    repository: UniverseRepository | None = None,
) -> tuple[ETFUniverseMember, ...]:
    normalized = normalize_etf_market(market)
    repo = repository or UniverseRepository()
    universe = repo.get_by_key(f"{normalized.lower()}_index_etf")
    if universe is None or not universe.enabled:
        raise ValueError(f"Enabled ETF Rotation universe not found for {normalized}")
    result = []
    for member in repo.list_members(universe.id):
        metadata = member.member_metadata or {}
        result.append(
            ETFUniverseMember(
                code=member.instrument.code,
                name=member.instrument.name,
                category=str(metadata.get("category", "")),
                theme=str(metadata.get("theme", "")),
                risk_group=str(metadata.get("risk_group", "")),
                market=normalized,
            )
        )
    return tuple(sorted(result, key=lambda item: item.code))


def enabled_etfs(market: str = "CN", repository: UniverseRepository | None = None) -> tuple[ETFUniverseMember, ...]:
    return get_etf_universe(market, repository)


def universe_by_code(market: str = "CN", repository: UniverseRepository | None = None) -> dict[str, ETFUniverseMember]:
    return {member.code: member for member in get_etf_universe(market, repository)}


__all__ = ["ETFUniverseMember", "enabled_etfs", "get_etf_universe", "normalize_etf_market", "universe_by_code"]
