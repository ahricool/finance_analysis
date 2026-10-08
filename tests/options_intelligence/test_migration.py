import importlib.util
from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from finance_analysis.database.models.options_intelligence import (
    OptionContract,
    OptionQuoteSnapshot,
    OptionDailyMetrics,
    OptionAnomalyEvent,
    OptionAnalysis,
)


def test_upgrade_and_downgrade_match_models():
    path = Path(__file__).parents[2] / "alembic/versions/0070_options_intelligence.py"
    spec = importlib.util.spec_from_file_location("options_revision", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0069_earnings_outlook"
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        for model in (OptionContract, OptionQuoteSnapshot, OptionDailyMetrics, OptionAnomalyEvent, OptionAnalysis):
            actual = {c["name"] for c in inspect(connection).get_columns(model.__tablename__)}
            assert actual == {c.name for c in model.__table__.columns}
            assert {
                tuple(c["column_names"]) for c in inspect(connection).get_unique_constraints(model.__tablename__)
            } == {
                tuple(col.name for col in cons.columns)
                for cons in model.__table__.constraints
                if cons.__class__.__name__ == "UniqueConstraint"
            }
        migration.downgrade()
        assert inspect(connection).get_table_names() == []
    engine.dispose()
