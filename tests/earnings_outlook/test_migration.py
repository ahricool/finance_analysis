from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, create_engine
from finance_analysis.database.models import FinanceEvent, Instrument


def test_migration_builds_and_reverses_only_new_earnings_tables():
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_heads() == ["0070_options_intelligence"]
    migration = scripts.get_revision("0069_earnings_outlook").module
    engine = create_engine("sqlite://")
    Instrument.__table__.create(engine)
    FinanceEvent.__table__.create(engine)
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        names = set(inspect(conn).get_table_names())
        assert {"earnings_research", "earnings_prediction", "earnings_outlook_state"} <= names
        unique = inspect(conn).get_unique_constraints("earnings_prediction")
        assert unique[0]["column_names"] == ["event_id", "stage", "input_hash"]
        migration.downgrade()
        assert set(inspect(conn).get_table_names()) == {"instrument", "finance_events"}
