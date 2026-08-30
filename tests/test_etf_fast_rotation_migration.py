from pathlib import Path

from finance_analysis.core.paths import PROJECT_ROOT  # pragma: allowlist secret
from finance_analysis.database.models.etf_rotation import (  # pragma: allowlist secret
    ETFMarketRotationSnapshot,
    ETFMomentumSnapshot,
)


def test_fast_rotation_schema_matches_new_strategy_semantics() -> None:
    momentum = set(ETFMomentumSnapshot.__table__.columns.keys())
    market = set(ETFMarketRotationSnapshot.__table__.columns.keys())
    assert {
        "ret_3d",
        "momentum_acceleration_3d",
        "momentum_acceleration_5d",
        "weighted_slope_5d",
        "weighted_slope_15d",
        "trend_quality_15d",
        "signed_efficiency_ratio_10d",
        "rs_5d",
        "rs_10d",
        "rs_20d",
    } <= momentum
    assert not {
        "ret_30d",
        "ret_60d",
        "ma60_ratio",
        "trend_quality_25d",
        "rs_60d",
        "risk_adjusted_momentum_60d",
        "max_drawdown_60d",
    } & momentum
    assert {"positive_5d_breadth", "above_ma10_breadth", "benchmark_ret_5d"} <= market
    assert not {"breadth_above_ma60", "benchmark_ma60_ratio"} & market


def test_fast_rotation_migration_follows_current_head_and_drops_slow_fields() -> None:
    source = (
        Path(PROJECT_ROOT) / "alembic" / "versions" / "0035_etf_fast_rotation.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: Union[str, Sequence[str], None] = "0034_trend_following_execution_context"' in source
    assert '"ret_30d"' in source and 'op.drop_column("etf_momentum_snapshot", name)' in source
    assert '"ret_3d"' in source and '"signed_efficiency_ratio_10d"' in source
