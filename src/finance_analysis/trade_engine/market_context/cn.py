# -*- coding: utf-8 -*-
"""CN MarketContext from already-persisted structure / sentiment / industry snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from finance_analysis.market_review.trading_calendar import get_market_now, is_market_open  # pragma: allowlist secret
from finance_analysis.trade_engine.bars import in_evaluation_window  # pragma: allowlist secret
from finance_analysis.trade_engine.models import MarketContext  # pragma: allowlist secret


def build_cn_market_context(*, now: datetime | None = None, db=None) -> MarketContext:
    current = now or get_market_now("cn")
    trading_date = current.date()
    warnings: list[str] = []
    structure = _read_structure("CN", db)
    sentiment = _read_sentiment(db)
    industry = _read_industry(db)
    breadth = {}
    indices = {}
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
        if structure.get("trade_date") and structure["trade_date"] != trading_date:
            warnings.append("structure_not_today")
    else:
        warnings.append("structure_unavailable")
    if industry:
        sectors = {
            "leaders": (industry.get("leaders") or industry.get("payload") or {}).get("leaders")
            if isinstance(industry.get("payload"), dict)
            else industry.get("leaders"),
            "laggers": industry.get("laggers"),
            "trade_date": str(industry.get("trade_date") or ""),
        }
    if sentiment:
        payload = sentiment if isinstance(sentiment, dict) else {}
        if regime is None:
            regime = (payload.get("result") or payload).get("emotion") or (payload.get("result") or payload).get("regime")
    return MarketContext(
        market="CN",
        as_of=current,
        trading_date=datetime.combine(trading_date, datetime.min.time(), tzinfo=current.tzinfo),
        session_open=bool(is_market_open("cn", trading_date) and in_evaluation_window("CN", current)),
        regime=regime,
        breadth=breadth,
        indices=indices,
        sectors=sectors or {},
        sentiment=sentiment if isinstance(sentiment, dict) else None,
        warnings=tuple(warnings),
    )


def _read_structure(market: str, db) -> dict[str, Any] | None:
    try:
        from finance_analysis.database.repositories.market_structure import MarketStructureRepository  # pragma: allowlist secret

        repo = MarketStructureRepository(market.lower(), db_manager=db) if db is not None else MarketStructureRepository(market.lower())
        return repo.read()
    except Exception:
        return None


def _read_sentiment(db) -> dict[str, Any] | None:
    try:
        from finance_analysis.database.repositories.market_sentiment import MarketSentimentRepository  # pragma: allowlist secret

        repo = MarketSentimentRepository(db) if db is not None else MarketSentimentRepository()
        row = repo.overview()
        if not isinstance(row, dict):
            return None
        return row
    except Exception:
        return None


def _read_industry(db) -> dict[str, Any] | None:
    try:
        from finance_analysis.database.repositories.industry_strength import IndustryStrengthRepository  # pragma: allowlist secret

        repo = IndustryStrengthRepository(db) if db is not None else IndustryStrengthRepository()
        rows = repo.ranking(limit=8)
        if not rows:
            return None
        return {"leaders": rows[:4], "laggers": list(reversed(rows[-4:])), "trade_date": rows[0].get("trade_date")}
    except Exception:
        return None
