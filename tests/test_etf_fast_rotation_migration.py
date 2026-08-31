import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

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
    assert 'down_revision: Union[str, Sequence[str], None] = "0034_trend_execution_context"' in source
    assert '"ret_30d"' in source and "batch_op.drop_column(name)" in source
    assert '"ret_3d"' in source and '"signed_efficiency_ratio_10d"' in source


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="database required")
def test_fast_rotation_migration_runs_on_database() -> None:
    path = Path(PROJECT_ROOT) / "alembic" / "versions" / "0035_etf_fast_rotation.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(os.environ["DATABASE_URL"])
    schema = f"etf_fast_rotation_{uuid.uuid4().hex}"
    try:
        connection_context = engine.connect()
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"database is unavailable: {exc.orig}")
    with connection_context as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(text(
                "CREATE TABLE etf_momentum_snapshot ("
                "id BIGINT PRIMARY KEY, rank_1d INTEGER NOT NULL, rank_5d INTEGER NOT NULL, "
                "rank_10d INTEGER NOT NULL, rank_20d INTEGER NOT NULL, "
                "pct_rank_1d FLOAT NOT NULL, pct_rank_5d FLOAT NOT NULL, "
                "pct_rank_10d FLOAT NOT NULL, pct_rank_20d FLOAT NOT NULL, "
                "ret_30d FLOAT, ret_60d FLOAT, rank_30d INTEGER, rank_60d INTEGER, "
                "pct_rank_30d FLOAT, pct_rank_60d FLOAT, momentum_acceleration FLOAT, ma60_ratio FLOAT, "
                "weighted_slope_25d FLOAT, annualized_slope_25d FLOAT, trend_r2_25d FLOAT, "
                "trend_quality_25d FLOAT, efficiency_ratio_20d FLOAT, rs_60d FLOAT, "
                "risk_adjusted_momentum_60d FLOAT, max_drawdown_60d FLOAT, risk_adjusted_score FLOAT, "
                "CONSTRAINT ck_etf_momentum_ranks_positive CHECK (rank_1d > 0), "
                "CONSTRAINT ck_etf_momentum_pct_ranks_range CHECK (pct_rank_1d BETWEEN 0 AND 100))"
            ))
            connection.execute(text(
                "CREATE TABLE etf_market_rotation_snapshot ("
                "id BIGINT PRIMARY KEY, breadth_above_ma20 FLOAT, breadth_above_ma60 FLOAT, "
                "breadth_ma20_above_ma60 FLOAT, benchmark_ma20_ratio FLOAT, benchmark_ma60_ratio FLOAT, "
                "benchmark_above_ma20 BOOLEAN, benchmark_above_ma60 BOOLEAN, "
                "benchmark_ma20_above_ma60 BOOLEAN)"
            ))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            momentum = {column["name"] for column in inspect(connection).get_columns("etf_momentum_snapshot")}
            market = {column["name"] for column in inspect(connection).get_columns("etf_market_rotation_snapshot")}
            assert {"ret_3d", "trend_quality_15d", "signed_efficiency_ratio_10d", "rs_10d"} <= momentum
            assert not {"ret_60d", "trend_quality_25d", "risk_adjusted_score"} & momentum
            assert {"positive_5d_breadth", "above_ma10_breadth"} <= market
            assert "breadth_above_ma60" not in market
        finally:
            transaction.rollback()
            engine.dispose()
