"""Point-in-time entry and momentum rankings reconstructed from daily bars."""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from finance_analysis.etf_rotation.backtest.types import OhlcvBar
from finance_analysis.etf_rotation.classifier import classify_state
from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig
from finance_analysis.etf_rotation.eligibility import is_absolute_trend_eligible, is_liquidity_eligible
from finance_analysis.etf_rotation.features import calculate_features
from finance_analysis.etf_rotation.models import DailyBar
from finance_analysis.etf_rotation.ranking import (
    FACTOR_RANK_DIRECTIONS,
    calculate_rank_changes,
    rank_cross_section,
    rank_features,
)
from finance_analysis.etf_rotation.risk import calculate_stop_loss_pct
from finance_analysis.etf_rotation.scoring import calculate_entry_score, calculate_factor_scores
from finance_analysis.etf_rotation.universe import ETFUniverseMember

RANK_CHANGE_OFFSETS = (1, 3, 5)


def entry_sort_key(row: Mapping[str, Any]) -> tuple[float, float, int, str]:
    return (-float(row["entry_score"]), -float(row["momentum_score"]), int(row["rank_5d"]), str(row["code"]))


def momentum_sort_key(row: Mapping[str, Any]) -> tuple[float, float, int, str]:
    return (-float(row["momentum_score"]), -float(row["entry_score"]), int(row["rank_5d"]), str(row["code"]))


def _as_daily_bars(bars: Sequence[OhlcvBar]) -> list[DailyBar]:
    return [
        DailyBar(trade_date=item.trade_date, close=item.close, volume=item.volume, amount=item.amount)
        for item in bars
    ]


def _bars_on_or_before(bars: Sequence[OhlcvBar], trade_date: date) -> Sequence[OhlcvBar]:
    dates = [item.trade_date for item in bars]
    index = bisect.bisect_right(dates, trade_date)
    window = bars[:index]
    if not window or window[-1].trade_date != trade_date:
        return ()
    return window


def _historical_rank_5d(history: Sequence[int]) -> dict[int, int]:
    return {offset: history[-offset] for offset in RANK_CHANGE_OFFSETS if len(history) >= offset}


def compute_entry_rankings(
    bars_by_code: Mapping[str, Sequence[OhlcvBar]],
    members: Sequence[ETFUniverseMember],
    *,
    config: ETFRotationConfig = DEFAULT_CONFIG,
) -> dict[date, list[dict[str, Any]]]:
    """Rebuild each session's cross-section.  Rank 1 is strongest.

    ``momentum_rank`` is the cross-sectional rank of Momentum Score.
    Rank changes use previously reconstructed sessions, never future bars.
    """
    member_by_code = {member.code: member for member in members}
    market = members[0].market if members else "CN"
    benchmark_code = config.benchmark_codes[market]
    ordered = {
        code: tuple(sorted(bars, key=lambda item: item.trade_date))
        for code, bars in bars_by_code.items()
    }
    trade_dates = sorted({bar.trade_date for bars in ordered.values() for bar in bars})
    rank_5d_history: dict[str, list[int]] = defaultdict(list)
    rankings: dict[date, list[dict[str, Any]]] = {}
    for trade_date in trade_dates:
        benchmark_history = _bars_on_or_before(ordered.get(benchmark_code, ()), trade_date)
        benchmark_features = (
            calculate_features(_as_daily_bars(benchmark_history[-80:]), config) if benchmark_history else None
        )
        feature_rows: list[dict[str, Any]] = []
        for code, member in member_by_code.items():
            history = _bars_on_or_before(ordered.get(code, ()), trade_date)
            if not history:
                continue
            features = calculate_features(_as_daily_bars(history[-80:]), config)
            if features is None:
                continue
            payload = features.to_dict()
            payload["rs_20d"] = (
                payload["ret_20d"] - benchmark_features.ret_20d if benchmark_features is not None else None
            )
            payload["rs_60d"] = (
                payload["ret_60d"] - benchmark_features.ret_60d if benchmark_features is not None else None
            )
            feature_rows.append(
                {
                    "trade_date": trade_date,
                    "code": code,
                    "name": member.name,
                    "category": member.category,
                    "theme": member.theme,
                    "risk_group": member.risk_group,
                    "relative_strength_ready": benchmark_features is not None,
                    **payload,
                }
            )
        if not feature_rows:
            continue
        ranked = rank_features(rank_cross_section(feature_rows), FACTOR_RANK_DIRECTIONS)
        evaluated: list[dict[str, Any]] = []
        for row in ranked:
            history = _historical_rank_5d(rank_5d_history[str(row["code"])])
            row.update(calculate_rank_changes(int(row["rank_5d"]), history))
            row.update(calculate_factor_scores(row, config))
            row["momentum_score"] = row["momentum_strength_score"]
            row["absolute_trend_eligible"] = is_absolute_trend_eligible(row, config)
            row["liquidity_eligible"] = is_liquidity_eligible(row, market, config)
            evaluated.append(row)
        evaluated = rank_features(evaluated, {"composite_score": True})
        for row in evaluated:
            row["rank"] = row.pop("rank_composite_score")
            row.pop("pct_rank_composite_score", None)
            composite_score = float(row["composite_score"] or 0.0)
            entry_score, components = calculate_entry_score(row, composite_score, config)
            row["entry_score"] = entry_score
            row["score_components"] = components
            row["state"] = classify_state(row, composite_score, config)
            row["stop_loss_pct"] = calculate_stop_loss_pct(float(row["realized_vol_20d"]), config)
        evaluated.sort(key=entry_sort_key)
        for index, row in enumerate(evaluated, start=1):
            row["entry_rank"] = index
            rank_5d_history[str(row["code"])].append(int(row["rank_5d"]))
        by_momentum = sorted(evaluated, key=momentum_sort_key)
        for index, row in enumerate(by_momentum, start=1):
            row["momentum_rank"] = index
        rankings[trade_date] = evaluated
    return rankings


__all__ = ["compute_entry_rankings", "entry_sort_key", "momentum_sort_key"]
