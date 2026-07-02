from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from sqlalchemy import create_engine, text

from alembic.migration import MigrationContext
from alembic.operations import Operations
from finance_analysis.core.paths import PROJECT_ROOT


def _load_migration() -> ModuleType:
    path = Path(PROJECT_ROOT) / "alembic" / "versions" / "0014_rename_us_signal_type.py"
    spec = importlib.util.spec_from_file_location("signal_type_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_signal_type_migration_upgrade_and_downgrade() -> None:
    migration = _load_migration()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE signal (id INTEGER PRIMARY KEY, signal_type VARCHAR(80))"))
        connection.execute(
            text(
                "INSERT INTO signal (id, signal_type) VALUES "
                "(1, 'relative_strength_failure'), (2, 'relative_strength_breakout')"
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        assert connection.execute(text("SELECT signal_type FROM signal WHERE id = 1")).scalar_one() == (
            "strong_to_weak_failure"
        )
        assert connection.execute(text("SELECT signal_type FROM signal WHERE id = 2")).scalar_one() == (
            "relative_strength_breakout"
        )

        migration.downgrade()
        assert connection.execute(text("SELECT signal_type FROM signal WHERE id = 1")).scalar_one() == (
            "relative_strength_failure"
        )
