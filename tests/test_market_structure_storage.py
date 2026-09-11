"""Executable migration and real SQL batch-query contracts, using isolated SQLite."""

from contextlib import contextmanager
from datetime import date, timedelta
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session

from finance_analysis.database.models.stock import Instrument, StockDaily
from finance_analysis.database.models.etf_rotation import ETFMomentumSnapshot
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot
from finance_analysis.database.repositories.market_structure import MarketStructureRepository
from finance_analysis.database.repositories.trend_following import TrendFollowingRepository

DAY = date(2026, 9, 1)


class Database:
    def __init__(self):
        self.engine = create_engine("sqlite://")

    @contextmanager
    def get_session(self):
        with Session(self.engine) as session:
            yield session


def test_migration_preserves_existing_rows_and_can_downgrade():
    path = Path(__file__).parents[1] / "alembic/versions/0050_market_structure_health.py"
    spec = importlib.util.spec_from_file_location("structure_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    db = Database()
    with db.engine.begin() as connection:
        connection.execute(text("CREATE TABLE trend_following_snapshot (id INTEGER PRIMARY KEY, alpha_score FLOAT)"))
        connection.execute(text("CREATE TABLE etf_momentum_snapshot (id INTEGER PRIMARY KEY, rank INTEGER)"))
        connection.execute(text("INSERT INTO trend_following_snapshot VALUES (1, 90)"))
        connection.execute(text("INSERT INTO etf_momentum_snapshot VALUES (1, 1)"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.execute(
            text(
                "SELECT alpha_score, trend_lifecycle, fragility_score, fragility_breakdown "
                "FROM trend_following_snapshot"
            )
        ).one() == (90, None, None, None)
        assert connection.execute(text("SELECT rank FROM etf_momentum_snapshot")).scalar() == 1
        constraints = inspect(connection).get_unique_constraints("market_structure_snapshot")
        assert constraints[0]["column_names"] == ["market", "trade_date"]
        migration.downgrade()
        assert connection.execute(text("SELECT alpha_score FROM trend_following_snapshot")).scalar() == 90
        assert "market_structure_snapshot" not in inspect(connection).get_table_names()


def test_real_queries_are_constant_count_and_point_in_time():
    db = Database()
    for model in (Instrument, StockDaily, ETFMomentumSnapshot, TrendFollowingSnapshot):
        model.__table__.create(db.engine)
    # Nullable scalar fixtures isolate the query contract from strategy execution fields.
    with db.engine.begin() as connection:
        connection.execute(text("DROP TABLE etf_momentum_snapshot"))
        connection.execute(
            text(
                "CREATE TABLE etf_momentum_snapshot "
                "(market TEXT, trade_date DATE, instrument_id INTEGER, rank INTEGER)"
            )
        )
        connection.execute(text("DROP TABLE trend_following_snapshot"))
        connection.execute(
            text(
                "CREATE TABLE trend_following_snapshot "
                "(market TEXT, trade_date DATE, code TEXT, features JSON, trend_lifecycle TEXT)"
            )
        )
        for offset in range(-1, 8):
            day = DAY - timedelta(days=offset)
            connection.execute(
                text("INSERT INTO etf_momentum_snapshot VALUES (:m, :d, 1, 1), (:m, :d, 2, 2)"), {"m": "US", "d": day}
            )
            connection.execute(
                text("INSERT INTO trend_following_snapshot VALUES ('US', :d, 'A.US', '{}', 'EMERGING')"), {"d": day}
            )
    statements = []
    event.listen(
        db.engine, "before_cursor_execute", lambda conn, cursor, stmt, params, context, many: statements.append(stmt)
    )
    repository = MarketStructureRepository("US", db)
    for size in (1, 500):
        statements.clear()
        assert repository.load_daily_history([f"{i}.US" for i in range(size)], DAY, calendar_lookback_days=90) == []
        rankings = repository.etf_rankings(DAY)
        assert len(statements) == 2
        assert max(rankings) == DAY
        assert len(rankings) == 6
    statements.clear()
    history = TrendFollowingRepository("US", db).health_history(DAY, {"A.US"})
    assert len(statements) == 1
    assert set(history["A.US"]) == {1, 2, 3, 4, 5}
    assert all(row["trade_date"] < DAY for row in history["A.US"].values())


def test_postgresql_migration_and_idempotent_upsert():
    """Opt in with a dedicated TEST_POSTGRES_URL; never use the application's database."""
    import os
    from uuid import uuid4
    import pytest

    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("dedicated TEST_POSTGRES_URL is required")
    engine = create_engine(url)
    schema = "test_structure_" + uuid4().hex
    path = Path(__file__).parents[1] / "alembic/versions/0050_market_structure_health.py"
    spec = importlib.util.spec_from_file_location("structure_migration_pg", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            connection.execute(text(f"SET LOCAL search_path TO {schema}"))
            connection.execute(text("CREATE TABLE trend_following_snapshot (id BIGINT PRIMARY KEY, alpha_score FLOAT)"))
            connection.execute(text("INSERT INTO trend_following_snapshot VALUES (1, 90)"))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

            class BoundDatabase:
                @contextmanager
                def get_session(self):
                    with Session(connection) as session:
                        yield session

                @contextmanager
                def session_scope(self):
                    with Session(connection) as session, session.begin():
                        yield session

            repo = MarketStructureRepository("US", BoundDatabase())
            payload = {
                "market": "US",
                "trade_date": DAY,
                "breadth_divergence_5d": 0.02,
                "metrics_json": {"version": "1"},
            }
            repo.save(payload)
            first = repo.read(DAY)
            repo.save({**payload, "breadth_divergence_5d": 0.03})
            second = repo.read(DAY)
            assert second["id"] == first["id"]
            assert second["created_at"] == first["created_at"]
            assert second["updated_at"] >= first["updated_at"]
            assert second["breadth_divergence_5d"] == pytest.approx(0.03)
            assert repo.read(DAY - timedelta(days=1)) is None
            assert connection.execute(
                text("SELECT alpha_score, fragility_score FROM trend_following_snapshot")
            ).one() == (90, None)
        finally:
            transaction.rollback()
    engine.dispose()
