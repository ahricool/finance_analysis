"""Security-master synchronization with safe primary-directory reconciliation."""

from dataclasses import dataclass

from finance_analysis.database.repositories.stock import InstrumentRepository


class InstrumentSyncService:
    def __init__(self, primary=None, fallback=None, instrument_repository=None):
        if primary is None:
            from finance_analysis.integrations.market_data.providers.akshare import AkShareProvider
            from finance_analysis.integrations.market_data.providers.tickflow import TickFlowFreeProvider

            primary = TickFlowFreeProvider()
            fallback = fallback or AkShareProvider()
        self.primary = primary
        self.fallback = fallback
        self.instruments = instrument_repository or InstrumentRepository()

    def sync_instruments(self, market: str) -> int:
        return self.sync_instruments_detailed(market).fetched

    def sync_instruments_detailed(self, market: str) -> "InstrumentSyncResult":
        """Reconcile a complete primary directory; fallback responses only upsert."""
        primary_complete = False
        provider = str(getattr(self.primary, "name", "primary")).upper()
        fallback_used = False
        try:
            records = self.primary.fetch_instruments(market)
            if not records:
                raise ValueError(f"Primary instrument provider returned no {market} securities")
            primary_complete = True
        except Exception:
            if self.fallback is None:
                raise
            records = self.fallback.fetch_instruments(market)
            provider = str(getattr(self.fallback, "name", "fallback")).upper()
            fallback_used = True
        if not records:
            raise ValueError(f"Instrument provider returned no {market} securities")
        codes = {record["code"] for record in records}
        existing = self.instruments.existing_codes(codes)
        self.instruments.upsert_symbols(records)
        delisted = 0
        if primary_complete:
            delisted = self.instruments.mark_missing_delisted(market, codes)
        return InstrumentSyncResult(
            fetched=len(records),
            inserted=len(codes - existing),
            updated=len(codes & existing),
            delisted=delisted,
            provider=provider,
            fallback_used=fallback_used,
        )


@dataclass(frozen=True)
class InstrumentSyncResult:
    fetched: int
    inserted: int
    updated: int
    delisted: int
    provider: str
    fallback_used: bool


__all__ = ["InstrumentSyncResult", "InstrumentSyncService"]
