from __future__ import annotations

import pandas as pd
import pytest

from qlib_worker.models.metrics import (
    classification_metrics,
    cross_section_metrics,
    cross_section_trading_metrics,
)
from qlib_worker.models.training import _final_n_estimators


def _panel(values: list[tuple[str, str, float, float]]) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp(day), code) for day, code, _, _ in values],
        names=["datetime", "instrument"],
    )
    return pd.DataFrame(
        {"prediction": [item[2] for item in values], "label": [item[3] for item in values]},
        index=index,
    )


def test_cross_section_metrics_use_daily_rank_ic_not_pooled_headline() -> None:
    frame = _panel(
        [
            ("2026-01-02", "A.US", 3.0, 2.0),
            ("2026-01-02", "B.US", 2.0, 1.0),
            ("2026-01-02", "C.US", 1.0, 0.0),
            ("2026-01-05", "A.US", 1.0, 2.0),
            ("2026-01-05", "B.US", 2.0, 1.0),
            ("2026-01-05", "C.US", 3.0, 0.0),
        ]
    )
    metrics = cross_section_metrics(frame)
    assert metrics["daily_rank_ic_mean"] == pytest.approx(0.0)
    assert metrics["rank_ic_positive_day_ratio"] == pytest.approx(0.5)
    assert metrics["top5_excess_return_pct"] is not None
    trading = cross_section_trading_metrics(frame, top_ks=(2,))
    assert trading["assumptions"]["prediction_horizon"] == 5
    assert trading["assumptions"]["periods_overlap"] is True
    assert trading["assumptions"]["not_a_backtest"] is True
    assert "one_way_cost_bps" not in trading["assumptions"]
    assert trading["top2_oos_return_pct"] == pytest.approx(1.0)
    assert trading["top2_positive_period_ratio"] == pytest.approx(1.0)
    assert "top2_simple_sharpe" not in trading
    assert "top2_max_drawdown" not in trading
    assert "top2_turnover" not in trading
    assert "top2_cost_adjusted_return_pct" not in trading
    assert "mae" in metrics and "rmse" in metrics


def test_classification_metrics_survive_single_class_folds() -> None:
    mixed = _panel(
        [
            ("2026-01-02", "A.US", 0.9, 1.0),
            ("2026-01-02", "B.US", 0.2, -1.0),
            ("2026-01-05", "A.US", 0.8, 2.0),
            ("2026-01-05", "B.US", 0.1, -0.5),
        ]
    )
    metrics, notes = classification_metrics(mixed)
    assert metrics["roc_auc"] is not None
    assert metrics["directional_hit_rate"] == pytest.approx(1.0)
    assert not notes

    single = _panel(
        [
            ("2026-01-02", "A.US", 0.9, 1.0),
            ("2026-01-02", "B.US", 0.2, 0.5),
        ]
    )
    metrics, notes = classification_metrics(single)
    assert metrics["roc_auc"] is None
    assert "single class" in notes[0]
    assert metrics["brier_score"] is not None


def test_final_n_estimators_uses_median_best_iteration() -> None:
    assert _final_n_estimators([40, 80, 120], 300) == 80
    assert _final_n_estimators([None, 0, None], 300) == 300
