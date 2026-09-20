# -*- coding: utf-8 -*-
"""US position-local intraday risk. Does not scan the market or compare to QQQ."""

from __future__ import annotations

from datetime import datetime

from ...core.time import utc_now  # pragma: allowlist secret
from ..models import PositionContext, TradeSignalCandidate  # pragma: allowlist secret
from ..position_metrics import local_bar_metrics  # pragma: allowlist secret

KEY = "us_position_intraday_v1"
VERSION = "1"


def _lte(value, threshold: float) -> bool:
    return value is not None and value <= threshold


class USPositionIntradayV1:
    key = KEY
    version = VERSION
    market = "US"

    def evaluate(self, context: PositionContext) -> list[TradeSignalCandidate]:
        if context.position.market != "US":
            return []
        metrics = local_bar_metrics(list(context.technical_indicators) or [])
        if not metrics:
            return []
        reasons: list[str] = []
        action = "WATCH"
        if (
            metrics.get("price_below_vwap")
            and _lte(metrics.get("change_5m"), -0.35)
            and _lte(metrics.get("change_15m"), -0.8)
            and (metrics.get("near_session_low") or metrics.get("broke_30m_low"))
        ):
            reasons.append("跌破VWAP并靠近盘中低点")
            if metrics.get("high_rvol"):
                action = "REDUCE"
                reasons.append("放量")
        elif metrics.get("price_below_vwap") and metrics.get("high_rvol") and _lte(metrics.get("change_5m"), -0.4):
            reasons.append("放量跌破VWAP")
        elif context.quote and context.quote.valid and context.position.average_cost > 0:
            pnl = (context.quote.price / context.position.average_cost - 1) * 100
            if pnl <= -5 and _lte(metrics.get("change_5m"), -0.35):
                reasons.append("持仓收益快速恶化")
        if not reasons:
            return []
        bar_end = metrics.get("bar_end")
        stamp = bar_end.isoformat() if isinstance(bar_end, datetime) else str(bar_end or "")
        signal_key = f"{KEY}:{context.position.position_id}:{action}:{stamp}"
        if context.strategy_state.get("last_signal_key") == signal_key:
            return []
        context.strategy_state["last_signal_key"] = signal_key
        now = context.now or utc_now()
        return [
            TradeSignalCandidate(
                market="US",
                account_id=context.position.account_id,
                position_id=context.position.position_id,
                symbol=context.position.symbol,
                strategy_key=KEY,
                strategy_version=VERSION,
                action=action,  # type: ignore[arg-type]
                suggested_target_quantity=None,
                severity="soft",
                reason=";".join(reasons),
                evidence={key: str(metrics[key]) for key in ("close", "vwap", "rvol", "change_5m", "change_15m") if metrics.get(key) is not None},
                evaluated_at=now,
                signal_key=signal_key,
            )
        ]
