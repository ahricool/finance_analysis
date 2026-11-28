"""Shared JSON representations for minute indicators."""
from decimal import Decimal
from typing import Any

from finance_analysis.core.time import utc_isoformat
from finance_analysis.integrations.market_data.realtime_state.models import TrendState
from finance_analysis.market_stream.patterns.models import PatternSignal, PatternState


def number(value: Decimal | int | None) -> float | int | None:
    if value is None:
        return None
    return int(value) if isinstance(value, int) else float(value)


def trend_payload(trend: TrendState) -> dict[str, Any]:
    return {
        "timeframe": trend.timeframe,
        "target_period": trend.target_period,
        "effective_period": trend.effective_period,
        "minimum_period": trend.minimum_period,
        "state": trend.state,
        "streak": trend.streak,
        "ma_value": number(trend.ma_value),
        "close": number(trend.close),
        "distance_pct": number(trend.distance_pct),
        "bar_time": utc_isoformat(trend.bar_time),
        "trading_date": trend.trading_date.isoformat() if trend.trading_date else None,
        "trade_session": trend.trade_session,
        "confirmed": trend.confirmed,
    }


def _pattern_signal_payload(signal: PatternSignal) -> dict[str, Any]:
    return {
        "timeframe": signal.timeframe,
        "pattern_type": signal.pattern_type,
        "pattern_name": signal.pattern_name,
        "direction": signal.direction,
        "stage": signal.stage,
        "quality_score": signal.quality_score,
        "occurred_at": utc_isoformat(signal.occurred_at),
        "confirmed_at": utc_isoformat(signal.confirmed_at),
        "trading_date": signal.trading_date.isoformat() if signal.trading_date else None,
        "trade_session": signal.trade_session,
        "bars_ago": signal.bars_ago,
        "session_minutes_ago": signal.session_minutes_ago,
        "reference_level": number(signal.reference_level),
        "invalidation_price": number(signal.invalidation_price),
        "reasons": list(signal.reasons),
        "confirmed": signal.confirmed,
    }


def pattern_payload(pattern: PatternState) -> dict[str, Any]:
    return {
        "timeframe": pattern.timeframe,
        "status": pattern.status,
        "trading_date": pattern.trading_date.isoformat() if pattern.trading_date else None,
        "bar_time": utc_isoformat(pattern.bar_time),
        "signal": _pattern_signal_payload(pattern.signal) if pattern.signal else None,
        "preview_status": pattern.preview_status,
        "preview_signal": _pattern_signal_payload(pattern.preview_signal) if pattern.preview_signal else None,
        "preview_bar_time": utc_isoformat(pattern.preview_bar_time),
        "preview_price": number(pattern.preview_price),
        "preview_updated_at": utc_isoformat(pattern.preview_updated_at),
    }
