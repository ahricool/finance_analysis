# -*- coding: utf-8 -*-
"""US MarketContext from persisted market-structure / ETF ranking snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from finance_analysis.market_review.trading_calendar import get_market_now, is_market_open  # pragma: allowlist secret
from finance_analysis.trade_engine.bars import in_evaluation_window  # pragma: allowlist secret
from finance_analysis.trade_engine.models import MarketContext  # pragma: allowlist secret


def build_us_market_context(*, now: datetime | None = None, db=None) -> MarketContext:
    current = now or get_market_now("us")
    trading_date = current.date()
    warnings: list[str] = []
    structure = _read_structure("US", db)
    breadth: dict[str, Any] = {}
    indices: dict[str, Any] = {}
    sectors: dict[str, Any] = {}
    regime = None
    if structure:
        breadth = {
            "member_positive_ratio_5d": structure.get("member_positive_ratio_5d"),
            "member_above_ma10_ratio": structure.get("member_above_ma10_ratio"),
            "member_above_ma20_ratio": structure.get("member_above_ma20_ratio"),
            "breadth_divergence_5d": structure.get("breadth_divergence_5d"),
        }
        indices = {
            "benchmark_return_5d": structure.get("benchmark_return_5d"),
            "median_member_return_5d": structure.get("median_member_return_5d"),
        }
        metrics = structure.get("metrics_json") or {}
        regime = metrics.get("regime") or metrics.get("market_regime")
        sectors = {"leadership_hhi_5d": structure.get("leadership_hhi_5d")}
        if structure.get("trade_date") and structure["trade_date"] != trading_date:
            warnings.append("structure_not_today")
    else:
        warnings.append("structure_unavailable")
    return MarketContext(
        market="US",
        as_of=current,
        trading_date=datetime.combine(trading_date, datetime.min.time(), tzinfo=current.tzinfo),
        session_open=bool(is_market_open("us", trading_date) and in_evaluation_window("US", current)),
        regime=regime,
        breadth=breadth,
        indices=indices,
        sectors=sectors,
        sentiment=None,
        warnings=tuple(warnings),
    )


def _read_structure(market: str, db) -> dict[str, Any] | None:
    try:
        from finance_analysis.database.repositories.market_structure import MarketStructureRepository  # pragma: allowlist secret

        repo = MarketStructureRepository(market.lower(), db_manager=db) if db is not None else MarketStructureRepository(market.lower())
        return repo.read()
    except Exception:
        return None
