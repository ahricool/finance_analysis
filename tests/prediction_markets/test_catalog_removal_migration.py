from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text, inspect


def test_retire_catalog_preserves_other_tasks_and_schema(monkeypatch):
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_current_head() == "0092_retire_prediction_catalog"
    migration = scripts.get_revision(scripts.get_current_head()).module
    # The deletion itself is portable; production/empty bootstrap also verified on PostgreSQL.
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for table in ("prediction_tag", "prediction_event", "instrument"):
            conn.execute(text(f"CREATE TABLE {table} (id INTEGER)"))
        conn.execute(text("CREATE TABLE task (task_type TEXT, scheduler_job_id TEXT)"))
        conn.execute(
            text(
                "INSERT INTO task VALUES ('scheduled_polymarket_catalog_sync', NULL), ('other','polymarket_catalog_sync'), ('keep','keep')"
            )
        )
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
        migration.upgrade()
        assert set(inspect(conn).get_table_names()) == {"instrument", "task"}
        assert conn.execute(text("SELECT task_type FROM task")).scalars().all() == ["keep"]
    engine.dispose()
