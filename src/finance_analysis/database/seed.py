"""Explicit one-time/reference-data seed helpers."""

from __future__ import annotations


def seed_nasdaq100_market_data_symbols(db_manager=None) -> int:
    """Idempotently seed Nasdaq-100 symbols using canonical ``.US`` codes.

    Runtime synchronization never reads the Python constituent constant; only
    this initialization boundary does.
    """
    from finance_analysis.database.repositories.stock import MarketDataSymbolRepository
    from finance_analysis.stocks.reference_data.stock_index import NASDAQ100_STOCK_INDEX

    return MarketDataSymbolRepository(db_manager).upsert_symbols(
        {
            "market": "US",
            "code": f"{ticker}.US",
            "name": name,
            "enabled": True,
            "sync_daily": True,
            "sync_minute": True,
        }
        for ticker, name in NASDAQ100_STOCK_INDEX.items()
    )
