"""Evaluate the shared intraday rules on rolling closed minutes."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from finance_analysis.integrations.market_data.realtime_state.models import CandleState
from finance_analysis.intraday_options.opportunities import calculate_opportunities
from finance_analysis.intraday_options.structure import calculate_structure
from finance_analysis.intraday_options.scoring import ROLLING_MINUTES, trend_summary
from finance_analysis.market_stream.indicator_payloads import pattern_payload, trend_payload
from finance_analysis.market_stream.patterns.config import PatternConfig
from finance_analysis.market_stream.patterns.detector import formal_pattern_state
from finance_analysis.market_stream.trend import rolling_ma_trend


def summarize(symbol, rows, now_ms):
    now = datetime.fromtimestamp(now_ms / 1000, UTC)
    opening = now.replace(second=0, microsecond=0) - timedelta(minutes=ROLLING_MINUTES)
    bars = []
    for row in rows:
        at = datetime.fromtimestamp(row["timestamp"] / 1000, UTC)
        close_time = at + timedelta(minutes=1)
        if row.get("closed") and opening <= at and close_time <= now:
            received = datetime.fromtimestamp(row.get("received_at_ms", row.get("event_time", 0)) / 1000, UTC)
            bars.append(CandleState(
                symbol=symbol, bar_time=at, confirmed=True, trade_session=None, received_at=max(received, close_time),
                source="binance", **{k: Decimal(str(row[k])) for k in ("open", "high", "low", "close", "turnover")},
                volume=row["volume"],
            ))
    if not bars:
        return None
    opening = bars[0].bar_time
    trend, windows = trend_summary(bars, opening)
    structure = calculate_structure(bars, opening=opening)
    primary = calculate_opportunities(bars, opening=opening)["primary"]
    start = len(bars)
    while start > 0 and bars[start - 1].is_valid():
        if start < len(bars) and bars[start].bar_time - bars[start - 1].bar_time != timedelta(minutes=1):
            break
        start -= 1
    tail = bars[start:]
    return {
        "trend_1m": trend_payload(rolling_ma_trend(tail, symbol, bars[-1].bar_time.date())),
        "pattern_1m": pattern_payload(formal_pattern_state(tail, None, bars[-1].bar_time.date(), PatternConfig())) if tail else None,
        "as_of": int(bars[-1].bar_time.timestamp() * 1000) + 60_000,
        "structure": {key: structure[key] for key in ("kind", "phase", "reference")},
        "score": trend["score"], "direction": trend.get("direction"), "state": trend.get("state"),
        "windows": {str(w["minutes"]): {
            "score": w["score"], "direction": w.get("direction"), "returnPct": w.get("return_pct"),
            "dataStatus": w["data_status"], "missingBars": w["missing_bars"], "availableBars": w["available_bars"],
        } for w in windows},
        "reference": any(w["data_status"] != "ready" for w in windows),
        "opportunity": primary and {k: primary[k] for k in ("quality_score", "direction", "kind", "trigger", "invalidation", "structure_id", "confirmed_at", "expires_at")},
    }
