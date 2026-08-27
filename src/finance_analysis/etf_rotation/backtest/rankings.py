"""Point-in-time entry-score rankings reconstructed from daily bars."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from finance_analysis.etf_rotation.backtest.types import OhlcvBar
from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig
from finance_analysis.etf_rotation.features import calculate_features
from finance_analysis.etf_rotation.models import DailyBar
from finance_analysis.etf_rotation.ranking import calculate_rank_changes, rank_cross_section
from finance_analysis.etf_rotation.scoring import calculate_entry_score, calculate_momentum_score
from finance_analysis.etf_rotation.universe import ETFUniverseMember

RANK_CHANGE_OFFSETS = (1, 3, 5)


def entry_sort_key(row: Mapping[str, Any]) -> tuple[float, float, int, str]:
    return (-float(row["entry_score"]), -float(row["momentum_score"]), int(row["rank_5d"]), str(row["code"]))


def _as_daily_bars(bars: Sequence[OhlcvBar]) -> list[DailyBar]:
    return [
        DailyBar(trade_date=item.trade_date, close=item.close, volume=item.volume, amount=item.amount) for item in bars
    ]


def _feature_rows_for_date(
    trade_date: date,
    bars_by_code: Mapping[str, Sequence[OhlcvBar]],
    members: Mapping[str, ETFUniverseMember],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code, member in members.items():
        history = [bar for bar in bars_by_code.get(code, ()) if bar.trade_date <= trade_date]
        if not history or history[-1].trade_date != trade_date:
            continue
        features = calculate_features(_as_daily_bars(history))
        if features is None:
            continue
        rows.append(
            {
                "trade_date": trade_date,
                "code": code,
                "name": member.name,
                "category": member.category,
                "theme": member.theme,
                "risk_group": member.risk_group,
                **features.to_dict(),
            }
        )
    return rows


def _historical_rank_5d(history: Sequence[int]) -> dict[int, int]:
    return {offset: history[-offset] for offset in RANK_CHANGE_OFFSETS if len(history) >= offset}


def compute_entry_rankings(
    bars_by_code: Mapping[str, Sequence[OhlcvBar]],
    members: Sequence[ETFUniverseMember],
    *,
    config: ETFRotationConfig = DEFAULT_CONFIG,
) -> dict[date, list[dict[str, Any]]]:
    """Return each session's full cross-section ranked by entry score.

    Rank 1 is the strongest entry.  ``rank_change_*d`` uses previously computed
    sessions from this reconstruction, not persisted snapshots.
    """
    member_by_code = {member.code: member for member in members}
    trade_dates = sorted(
        {bar.trade_date for bars in bars_by_code.values() for bar in bars if bar.trade_date}
    )
    rank_5d_history: dict[str, list[int]] = defaultdict(list)
    rankings: dict[date, list[dict[str, Any]]] = {}
    for trade_date in trade_dates:
        feature_rows = _feature_rows_for_date(trade_date, bars_by_code, member_by_code)
        if not feature_rows:
            continue
        ranked = rank_cross_section(feature_rows)
        evaluated: list[dict[str, Any]] = []
        for row in ranked:
            history = _historical_rank_5d(rank_5d_history[str(row["code"])])
            row.update(calculate_rank_changes(int(row["rank_5d"]), history))
            momentum_score = calculate_momentum_score(row, config)
            entry_score, components = calculate_entry_score(row, momentum_score, config)
            row["momentum_score"] = momentum_score
            row["entry_score"] = entry_score
            row["score_components"] = components
            evaluated.append(row)
        evaluated.sort(key=entry_sort_key)
        for index, row in enumerate(evaluated, start=1):
            row["entry_rank"] = index
            rank_5d_history[str(row["code"])].append(int(row["rank_5d"]))
        rankings[trade_date] = evaluated
    return rankings


__all__ = ["compute_entry_rankings", "entry_sort_key"]
