"""Fixed strategy set A-I.  No parameter search."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from finance_analysis.etf_rotation.backtest.types import OpenPosition, StrategySpec

STRATEGIES: tuple[StrategySpec, ...] = (
    StrategySpec("A_baseline", "Baseline Entry#1 / hold top2", max_positions=1, buy_entry_rank=1, exit_entry_rank=2),
    StrategySpec(
        "B_entry1_mom10",
        "Entry#1 + Momentum>10 exit",
        max_positions=1,
        buy_entry_rank=1,
        exit_momentum_rank=10,
    ),
    StrategySpec(
        "C_entry1_mom20",
        "Entry#1 + Momentum>20 exit",
        max_positions=1,
        buy_entry_rank=1,
        exit_momentum_rank=20,
    ),
    StrategySpec(
        "D_top3_mom10",
        "Entry Top3 EW + Momentum>10 exit",
        max_positions=3,
        buy_entry_rank=3,
        exit_momentum_rank=10,
    ),
    StrategySpec(
        "E_top3_mom20",
        "Entry Top3 EW + Momentum>20 exit",
        max_positions=3,
        buy_entry_rank=3,
        exit_momentum_rank=20,
    ),
    StrategySpec(
        "F_top3_absolute",
        "Top3 + absolute momentum filter",
        max_positions=3,
        buy_entry_rank=3,
        absolute_filter=True,
        exit_momentum_rank=20,
        exit_weak=True,
    ),
    StrategySpec(
        "G_f_stop",
        "F + trailing volatility stop",
        max_positions=3,
        buy_entry_rank=3,
        absolute_filter=True,
        exit_momentum_rank=20,
        exit_weak=True,
        stop_loss=True,
        trailing_stop=True,
    ),
    StrategySpec(
        "H_f_riskoff",
        "F + breadth risk-off",
        max_positions=3,
        buy_entry_rank=3,
        absolute_filter=True,
        exit_momentum_rank=20,
        exit_weak=True,
        risk_off=True,
    ),
    StrategySpec(
        "I_hysteresis",
        "Hysteresis Top3",
        max_positions=3,
        buy_entry_rank=3,
        exit_weak=True,
        hysteresis=True,
    ),
)

RISK_OFF_THRESHOLD = 0.30


def ranking_by_code(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(row["code"]): row for row in rows}


def market_is_risk_off(rows: Sequence[Mapping[str, Any]], threshold: float = RISK_OFF_THRESHOLD) -> bool:
    if not rows:
        return False
    positive_5d = sum(1 for row in rows if float(row["ret_5d"]) > 0) / len(rows)
    above_ma20 = sum(1 for row in rows if float(row["ma20_ratio"]) > 0) / len(rows)
    return positive_5d < threshold and above_ma20 < threshold


def breadth_stats(rows: Sequence[Mapping[str, Any]]) -> tuple[float, float]:
    if not rows:
        return 0.0, 0.0
    positive_5d = sum(1 for row in rows if float(row["ret_5d"]) > 0) / len(rows)
    above_ma20 = sum(1 for row in rows if float(row["ma20_ratio"]) > 0) / len(rows)
    return positive_5d, above_ma20


def passes_buy_filter(row: Mapping[str, Any], spec: StrategySpec) -> bool:
    if int(row["entry_rank"]) > spec.buy_entry_rank:
        return False
    if spec.absolute_filter and (float(row["ret_5d"]) <= 0 or float(row["ma20_ratio"]) <= 0):
        return False
    if spec.exit_weak and str(row["state"]) == "WEAK":
        return False
    if spec.exit_momentum_rank is not None and int(row["momentum_rank"]) > spec.exit_momentum_rank:
        return False
    if spec.hysteresis and int(row["momentum_rank"]) > spec.hysteresis_observe_rank:
        return False
    return True


def buy_candidates(rows: Sequence[Mapping[str, Any]], spec: StrategySpec) -> list[str]:
    eligible = [row for row in rows if passes_buy_filter(row, spec)]
    eligible.sort(key=lambda row: int(row["entry_rank"]))
    return [str(row["code"]) for row in eligible]


def exit_reason(
    position: OpenPosition,
    row: Mapping[str, Any] | None,
    spec: StrategySpec,
) -> str | None:
    if position.stop_hit:
        return "stop"
    if row is None:
        return "missing_signal"
    if spec.exit_weak and str(row["state"]) == "WEAK":
        return "weak"
    if spec.exit_entry_rank is not None and int(row["entry_rank"]) > spec.exit_entry_rank:
        return "entry_rank"
    if spec.hysteresis:
        momentum_rank = int(row["momentum_rank"])
        if momentum_rank > spec.hysteresis_observe_rank and position.mom_gt_exit_streak >= spec.hysteresis_exit_days:
            return "hysteresis"
        return None
    if spec.exit_momentum_rank is not None and int(row["momentum_rank"]) > spec.exit_momentum_rank:
        return "momentum"
    return None


def update_hysteresis_streak(position: OpenPosition, row: Mapping[str, Any] | None, spec: StrategySpec) -> None:
    if not spec.hysteresis or row is None:
        return
    if int(row["momentum_rank"]) > spec.hysteresis_observe_rank:
        position.mom_gt_exit_streak += 1
    else:
        position.mom_gt_exit_streak = 0


__all__ = [
    "STRATEGIES",
    "buy_candidates",
    "breadth_stats",
    "exit_reason",
    "market_is_risk_off",
    "passes_buy_filter",
    "ranking_by_code",
    "update_hysteresis_streak",
]
