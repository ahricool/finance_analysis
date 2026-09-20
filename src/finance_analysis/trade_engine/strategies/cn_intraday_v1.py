# -*- coding: utf-8 -*-
"""CN holdings-related intraday warnings from shared MarketContext. Not a scanner."""

from __future__ import annotations

from typing import Any, Sequence

from finance_analysis.portfolio.models import ResolvedPosition  # pragma: allowlist secret
from finance_analysis.trade_engine.models import MarketContext, QuoteView, TradeSignal  # pragma: allowlist secret

KEY = "cn_intraday_v1"
VERSION = "1"
STRESS = {"panic", "cold", "divergent"}


class CNIntradayV1:
    key = KEY
    version = VERSION
    market = "CN"

    def evaluate(
        self,
        position: ResolvedPosition,
        market_context: MarketContext,
        quote: QuoteView | None,
        bars: Sequence,
        state: dict[str, Any],
    ) -> list[TradeSignal]:
        del quote, bars
        regime = (market_context.regime or "unknown").lower()
        reasons = []
        if regime in STRESS:
            reasons.append(f"市场状态={regime}")
        if "structure_unavailable" in market_context.warnings:
            reasons.append("缺少市场结构快照")
        if not reasons:
            state["last_regime"] = regime
            return []
        day = None if market_context.trading_date is None else market_context.trading_date.date().isoformat()
        signal_key = f"{KEY}:{position.position_id}:{day}:{regime}"
        if state.get("last_signal_key") == signal_key:
            return []
        state["last_signal_key"] = signal_key
        state["last_regime"] = regime
        return [
            TradeSignal(
                strategy_key=KEY,
                strategy_version=VERSION,
                market="CN",
                account_id=position.account_id,
                position_id=position.position_id,
                symbol=position.symbol,
                action="WARNING",
                suggested_target_quantity=None,
                reason=";".join(reasons),
                evidence={"regime": regime, "warnings": list(market_context.warnings)},
                evaluated_at=market_context.as_of,
                signal_key=signal_key,
            )
        ]
