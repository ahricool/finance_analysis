"""Security-master and current index-membership synchronization."""

from finance_analysis.database.repositories.stock import InstrumentRepository
from finance_analysis.database.repositories.universe import UniverseRepository


class InstrumentSyncService:
    def __init__(self, primary=None, fallback=None, instrument_repository=None, universe_repository=None):
        if primary is None:
            from finance_analysis.integrations.market_data.providers.akshare import AkShareProvider
            from finance_analysis.integrations.market_data.providers.tickflow import TickFlowFreeProvider

            primary = TickFlowFreeProvider()
            fallback = fallback or AkShareProvider()
        self.primary = primary
        self.fallback = fallback
        self.instruments = instrument_repository or InstrumentRepository()
        self.universes = universe_repository or UniverseRepository()

    def sync_instruments(self, market: str) -> int:
        """Upsert a successful provider response; never clear rows on failure."""
        try:
            records = self.primary.fetch_instruments(market)
        except Exception:
            if self.fallback is None:
                raise
            records = self.fallback.fetch_instruments(market)
        if not records:
            raise ValueError(f"Instrument provider returned no {market} securities")
        return self.instruments.upsert_symbols(records)

    def sync_csi_members(self, provider) -> dict[str, int]:
        fetched = {}
        for index_code, universe_key in (("000300", "cn_csi300"), ("000905", "cn_csi500"), ("000852", "cn_csi1000")):
            members = provider.fetch_index_members(index_code)
            if not members:
                raise ValueError(f"Index provider returned no members for {index_code}")
            fetched[universe_key] = members
        return {
            key: self.universes.replace_members(key, members, "AKSHARE")
            for key, members in fetched.items()
        }


__all__ = ["InstrumentSyncService"]
