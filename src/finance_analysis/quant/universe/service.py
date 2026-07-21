"""Synchronize the two fixed quantitative universes from project reference data."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.database.repositories.stock import MarketDataSymbolRepository
from finance_analysis.quant.markets import get_quant_market_config
from finance_analysis.stocks.market_scope import MarketDataScopeResolver
from finance_analysis.stocks.reference_data.stock_index import CSI300_STOCK_INDEX, SP500_STOCK_INDEX

logger = logging.getLogger(__name__)

US_SECTOR_BENCHMARKS = {
    "basic materials": "XLB.US",
    "communication services": "XLC.US",
    "consumer cyclical": "XLY.US",
    "consumer defensive": "XLP.US",
    "energy": "XLE.US",
    "financial services": "XLF.US",
    "healthcare": "XLV.US",
    "industrials": "XLI.US",
    "real estate": "XLRE.US",
    "technology": "XLK.US",
    "utilities": "XLU.US",
}


@dataclass(frozen=True)
class SectorClassification:
    sector_key: str | None
    sector_benchmark_code: str | None
    source: str
    reason: str | None = None


class QuantSectorClassifier:
    """Reuse existing providers and return auditable, cacheable classifications."""

    def __init__(self, cn_manager: Any = None):
        self._cn_manager = cn_manager

    def classify(self, market: str, code: str) -> SectorClassification:
        if market == "CN":
            return self._classify_cn(code)
        return self._classify_us(code)

    def _classify_cn(self, code: str) -> SectorClassification:
        if self._cn_manager is None:
            from finance_analysis.integrations.market_data.base import DataFetcherManager

            self._cn_manager = DataFetcherManager()
        boards = self._cn_manager.get_belong_boards(code.rsplit(".", 1)[0])
        industry = next(
            (
                board
                for board in boards
                if "行业" in str(board.get("type") or "")
                or str(board.get("type") or "").lower() == "industry"
            ),
            boards[0] if boards else None,
        )
        if not industry or not str(industry.get("name") or "").strip():
            return SectorClassification(None, None, "efinance_belong_board", "industry mapping unavailable")
        key = str(industry["name"]).strip()
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        return SectorClassification(key, f"CN-SECTOR-{digest}", "efinance_belong_board")

    @staticmethod
    def _classify_us(code: str) -> SectorClassification:
        try:
            import yfinance as yf

            info = yf.Ticker(code.removesuffix(".US")).info or {}
            sector = str(info.get("sector") or "").strip()
        except Exception as exc:
            logger.info("US sector classification failed code=%s reason=%s", code, exc)
            return SectorClassification(None, None, "yfinance_ticker_info", str(exc))
        benchmark = US_SECTOR_BENCHMARKS.get(sector.lower())
        if not sector or not benchmark:
            return SectorClassification(None, None, "yfinance_ticker_info", f"unsupported sector={sector or 'missing'}")
        return SectorClassification(sector, benchmark, "yfinance_ticker_info")


class FixedUniverseService:
    """Synchronize a fixed index universe without rewriting historical periods."""

    def __init__(
        self,
        repository: QuantRepository | None = None,
        symbol_repository: MarketDataSymbolRepository | None = None,
        classifier: Any = None,
    ):
        self.repository = repository or QuantRepository()
        self.symbol_repository = symbol_repository or MarketDataSymbolRepository()
        self.classifier = classifier or QuantSectorClassifier()

    @staticmethod
    def constituent_codes(market: str) -> frozenset[str]:
        """Return canonical members from the checked-in index constituent variables."""
        normalized_market = str(market or "").strip().upper()
        if normalized_market == "US":
            reference = SP500_STOCK_INDEX
        elif normalized_market == "CN":
            reference = CSI300_STOCK_INDEX
        else:
            raise ValueError(f"Unsupported market={market}; expected US or CN")
        return frozenset(
            MarketDataScopeResolver.canonical_code(code, normalized_market)
            for code in reference
        )

    def refresh(self, market: str, effective_from: date) -> dict[str, Any]:
        config = get_quant_market_config(market)
        constituent_codes = self.constituent_codes(config.market)
        universe = self.repository.upsert_universe(
            {
                "key": config.default_universe,
                "name": "S&P 500" if config.market == "US" else "沪深300",
                "market": config.market,
                "description": (
                    "Fixed S&P 500 constituents from SP500_STOCK_INDEX."
                    if config.market == "US"
                    else "Fixed CSI 300 constituents from CSI300_STOCK_INDEX."
                ),
                "enabled": True,
                "is_dynamic": False,
                "benchmark_code": config.primary_benchmark,
                "sector_benchmark_mode": "member_or_synthetic",
                "config": {
                    "constituent_source": (
                        "SP500_STOCK_INDEX" if config.market == "US" else "CSI300_STOCK_INDEX"
                    ),
                },
            }
        )
        symbols = self.symbol_repository.list_enabled_daily_by_codes(config.market, constituent_codes)
        by_code = {symbol.code: symbol for symbol in symbols}
        missing_symbols = sorted(constituent_codes - set(by_code))
        previous = self.repository.latest_member_mappings(universe.id)
        mappings: dict[int, dict[str, Any]] = {}
        missing_sectors: list[dict[str, str]] = []
        sources: dict[str, int] = {}
        for symbol in symbols:
            old = previous.get(symbol.id)
            if old and old.get("sector_key") and old.get("sector_benchmark_code"):
                mappings[symbol.id] = old
                sources[old.get("source") or "persisted"] = sources.get(old.get("source") or "persisted", 0) + 1
                continue
            classification = self.classifier.classify(config.market, symbol.code)
            mappings[symbol.id] = {
                "sector_key": classification.sector_key,
                "sector_benchmark_code": classification.sector_benchmark_code,
                "source": classification.source,
            }
            sources[classification.source] = sources.get(classification.source, 0) + 1
            if not classification.sector_key or not classification.sector_benchmark_code:
                missing_sectors.append(
                    {"code": symbol.code, "reason": classification.reason or "industry mapping unavailable"}
                )
        counts = self.repository.sync_fixed_members(universe.id, symbols, mappings, effective_from)
        mapped = len(symbols) - len(missing_sectors)
        coverage = mapped / len(symbols) if symbols else 0.0
        universe_config = dict(universe.config or {})
        universe_config.update(
            {
                "constituent_count": len(constituent_codes),
                "available_symbol_count": len(symbols),
                "sector_mapped_count": mapped,
                "sector_mapping_coverage": coverage,
                "sector_mapping_sources": sources,
                "missing_symbols": missing_symbols,
                "missing_sector_mappings": missing_sectors[:100],
            }
        )
        self.repository.update_universe(universe.id, config=universe_config)
        return {
            "market": config.market,
            "universe": config.default_universe,
            "constituent_codes": sorted(constituent_codes),
            "member_count": len(symbols),
            "sector_mapped_count": mapped,
            "sector_mapping_coverage": coverage,
            "missing_symbols": missing_symbols,
            "missing_sector_mappings": missing_sectors,
            **counts,
        }


__all__ = ["FixedUniverseService", "QuantSectorClassifier", "SectorClassification", "US_SECTOR_BENCHMARKS"]
