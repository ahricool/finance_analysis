"""Standalone realtime market streaming service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from finance_analysis.market_stream.service import MarketStreamService

__all__ = ["MarketStreamService"]


def __getattr__(name: str) -> Any:
    if name == "MarketStreamService":
        from finance_analysis.market_stream.service import MarketStreamService

        return MarketStreamService
    raise AttributeError(name)
