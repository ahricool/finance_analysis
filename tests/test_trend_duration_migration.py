from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from finance_analysis.core.paths import PROJECT_ROOT  # pragma: allowlist secret
from finance_analysis.database.models.etf_rotation import ETFMomentumSnapshot  # pragma: allowlist secret
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot  # pragma: allowlist secret


def test_trend_duration_is_current_head_and_nullable_on_orm() -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0049_notification_center"
    assert ETFMomentumSnapshot.__table__.c.trend_duration_days.nullable is True
    assert TrendFollowingSnapshot.__table__.c.trend_duration_days.nullable is True


def test_trend_duration_migration_leaves_existing_rows_null() -> None:
    path = Path(PROJECT_ROOT) / "alembic" / "versions" / "0048_trend_duration_days.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE etf_momentum_snapshot (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE trend_following_snapshot (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO etf_momentum_snapshot (id) VALUES (1)"))
        connection.execute(text("INSERT INTO trend_following_snapshot (id) VALUES (1)"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        etf_columns = {column["name"]: column for column in inspect(connection).get_columns("etf_momentum_snapshot")}
        trend_columns = {
            column["name"]: column for column in inspect(connection).get_columns("trend_following_snapshot")
        }
        assert etf_columns["trend_duration_days"]["nullable"] is True
        assert trend_columns["trend_duration_days"]["nullable"] is True
        assert connection.execute(text("SELECT trend_duration_days FROM etf_momentum_snapshot")).scalar() is None
        assert connection.execute(text("SELECT trend_duration_days FROM trend_following_snapshot")).scalar() is None
