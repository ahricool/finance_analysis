"""Orchestration for the single weekly reference-data synchronization job."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

from finance_analysis.database.repositories.stock import InstrumentRepository
from finance_analysis.database.repositories.universe import UniverseRepository
from finance_analysis.integrations.market_data.instrument_sync import InstrumentSyncService
from finance_analysis.integrations.market_data.providers.akshare import AkShareProvider
from finance_analysis.integrations.market_data.providers.tickflow import TickFlowFreeProvider
from finance_analysis.integrations.market_data.providers.us_index_constituents import USIndexConstituentProvider


@dataclass(frozen=True)
class IndexUniverseSyncConfig:
    provider: str
    index_code: str


INDEX_UNIVERSE_SYNC_CONFIG = {
    "cn_csi300": IndexUniverseSyncConfig("AKSHARE", "000300"),
    "cn_csi500": IndexUniverseSyncConfig("AKSHARE", "000905"),
    "cn_csi1000": IndexUniverseSyncConfig("AKSHARE", "000852"),
    "us_sp500": IndexUniverseSyncConfig("WIKIPEDIA", "SP500"),
    "us_nasdaq100": IndexUniverseSyncConfig("WIKIPEDIA", "NASDAQ100"),
}


class ReferenceDataSyncService:
    def __init__(
        self,
        *,
        instrument_repository: InstrumentRepository | None = None,
        universe_repository: UniverseRepository | None = None,
        instrument_primary: Any = None,
        instrument_fallback: Any = None,
        index_providers: dict[str, Any] | None = None,
    ) -> None:
        self.instruments = instrument_repository or InstrumentRepository()
        self.universes = universe_repository or UniverseRepository()
        self.instrument_sync = InstrumentSyncService(
            instrument_primary or TickFlowFreeProvider(),
            instrument_fallback or AkShareProvider(),
            instrument_repository=self.instruments,
        )
        self.index_providers = index_providers or {
            "AKSHARE": AkShareProvider(),
            "WIKIPEDIA": USIndexConstituentProvider(),
        }

    def run(self) -> dict[str, Any]:
        started = monotonic()
        fetched = inserted = updated = fallback_count = 0
        providers: dict[str, str] = {}
        failed_markets: dict[str, str] = {}
        for market in ("CN", "US", "HK"):
            try:
                result = self.instrument_sync.sync_instruments_detailed(market)
                fetched += result.fetched
                inserted += result.inserted
                updated += result.updated
                fallback_count += int(result.fallback_used)
                providers[f"instrument:{market}"] = result.provider
            except Exception as exc:
                failed_markets[market] = str(exc)

        member_inserted = member_deleted = 0
        successful_universes = 0
        failed_universes: dict[str, str] = {}
        for key, config in INDEX_UNIVERSE_SYNC_CONFIG.items():
            try:
                provider = self.index_providers[config.provider]
                members = provider.fetch_index_members(config.index_code)
                if not members:
                    raise ValueError(f"Provider returned no members for {key}")
                self.instruments.upsert_symbols(members)
                stats = self.universes.replace_members_with_stats(key, members, config.provider)
                successful_universes += 1
                member_inserted += stats.inserted
                member_deleted += stats.deleted
                providers[f"universe:{key}"] = config.provider
            except Exception as exc:
                failed_universes[key] = str(exc)

        return {
            "sync_status": "success" if not failed_markets and not failed_universes else "partial",
            "instrument_fetched": fetched,
            "instrument_inserted": inserted,
            "instrument_updated": updated,
            "universe_count": successful_universes,
            "universe_member_inserted": member_inserted,
            "universe_member_deleted": member_deleted,
            "provider": providers,
            "fallback_count": fallback_count,
            "failed_markets": failed_markets,
            "failed_universes": failed_universes,
            "duration": round(monotonic() - started, 3),
        }


__all__ = ["INDEX_UNIVERSE_SYNC_CONFIG", "ReferenceDataSyncService"]
