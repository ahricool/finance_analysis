"""Security-master synchronization with safe primary-directory reconciliation."""

from dataclasses import dataclass

from finance_analysis.database.repositories.stock import InstrumentRepository


class InstrumentSyncService:
    def __init__(self, primary=None, fallback=None, instrument_repository=None):
        if primary is None:
            from finance_analysis.integrations.market_data.providers.longbridge.market import LongbridgeProvider
            from finance_analysis.integrations.market_data.providers.tickflow import TickFlowFreeProvider

            primary = TickFlowFreeProvider()
            # Security Master only. CN daily remains TickFlow; US daily remains
            # yfinance -> TickFlow. Never wire Longbridge into daily history.
            fallback = fallback or LongbridgeProvider()
        self.primary = primary
        self.fallback = fallback
        self.instruments = instrument_repository or InstrumentRepository()

    def ensure_instruments(self, codes: set[str]) -> None:
        """Resolve missing identities from security providers, never index records."""
        from finance_analysis.integrations.market_data.models import InstrumentRequest

        missing = codes - self.instruments.existing_codes(codes)
        for provider in (self.primary, self.fallback):
            if not missing or provider is None:
                continue
            try:
                result = provider.get_instrument_info(InstrumentRequest(tuple(sorted(missing))))
            except Exception:
                continue
            records = []
            for code in missing:
                info = result.data.get(code)
                kind = str(info.instrument_type or "").upper() if info else ""
                if kind not in {"STOCK", "ETF", "INDEX"}:
                    continue
                records.append(
                    {
                        "market": info.market.value,
                        "code": code,
                        "native_code": code.rsplit(".", 1)[0],
                        "name": info.name,
                        "instrument_type": kind,
                        "currency": info.currency,
                        "source": info.provider.upper(),
                    }
                )
            if records:
                self.instruments.upsert_symbols(records)
                missing -= {record["code"] for record in records}
        if missing:
            raise ValueError(f"Security Master metadata unavailable: {sorted(missing)}")

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
