"""Evaluate the shared intraday rules within a continuous UTC trading day."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from finance_analysis.integrations.market_data.realtime_state.models import CandleState
from finance_analysis.intraday_options.opportunities import calculate_opportunities
from finance_analysis.intraday_options.structure import calculate_structure
from finance_analysis.intraday_options.scoring import trend_summary


def summarize(symbol, rows, now_ms):
    now = datetime.fromtimestamp(now_ms / 1000, UTC)
    opening = now.replace(hour=0, minute=0, second=0, microsecond=0)
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
    trend, windows = trend_summary(bars, opening)
    structure = calculate_structure(bars, opening=opening)
    primary = calculate_opportunities(bars, opening=opening)["primary"]
    if any(w["data_status"] == "gap" for w in windows):
        primary = None
    return {
        "as_of": int(bars[-1].bar_time.timestamp() * 1000) + 60_000,
        "structure": {key: structure[key] for key in ("kind", "phase", "reference")},
        "score": trend["score"], "direction": trend.get("direction"), "state": trend.get("state"),
        "windows": {str(w["minutes"]): {
            "score": w["score"], "direction": w.get("direction"), "returnPct": w.get("return_pct"),
            "dataStatus": w["data_status"], "missingBars": w["missing_bars"], "availableBars": w["available_bars"],
        } for w in windows},
        "reference": any(w["data_status"] != "ready" for w in windows),
        "opportunity": primary and {k: primary[k] for k in ("quality_score", "direction", "kind")},
    }
