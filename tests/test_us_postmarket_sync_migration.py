"""Existing databases gain review inputs without changing strategy pools or history."""

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from finance_analysis.database.index_etf import seed_index_etf_universes
from finance_analysis.database.models.stock import Instrument, StockDaily
from finance_analysis.database.models.universe import Universe, UniverseInclude, UniverseMember
from finance_analysis.database.repositories.universe import UniverseRepository, UniverseResolver
from finance_analysis.market_review.us_postmarket_symbols import US_POSTMARKET_BENCHMARKS, US_POSTMARKET_SECTOR_ETFS
from finance_analysis.tasks.celery.jobs.market_data_sync.service import MarketDataSyncService


def test_migration_is_idempotent_and_preserves_existing_memberships_and_history():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    for model in (Instrument, StockDaily, Universe, UniverseMember, UniverseInclude):
        model.__table__.create(engine)

    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session

    db = SimpleNamespace(get_session=get_session)
    resolver = UniverseResolver(UniverseRepository(db))
    try:
        with engine.begin() as conn:
            seed_index_etf_universes(conn)
            conn.execute(Universe.__table__.insert().values(
                key="us_daily_sync", name="sync", market="US", universe_type="STRATEGY",
            ))
            sync_id = conn.scalar(select(Universe.id).where(Universe.key == "us_daily_sync"))
            spy_id = conn.scalar(select(Instrument.id).where(Instrument.code == "SPY.US"))
            conn.execute(UniverseMember.__table__.insert().values(
                universe_id=sync_id, instrument_id=spy_id, source="EXISTING", metadata={"keep": True},
            ))
        etfs_before = {item.code: item.id for item in resolver.resolve_universe("us_index_etf")}
        scripts = ScriptDirectory.from_config(Config("alembic.ini"))
        assert scripts.get_heads() == ["0068_us_postmarket_sync"]
        migration = scripts.get_revision("0068_us_postmarket_sync").module
        with engine.begin() as conn:
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
            migration.upgrade()
        required = set(US_POSTMARKET_BENCHMARKS) | set(US_POSTMARKET_SECTOR_ETFS)
        sync = MarketDataSyncService(market="US", universe_resolver=resolver,
                                     stock_repository=SimpleNamespace(), market_data_service=SimpleNamespace())
        assert {item.code for item in sync.load_scope()} == required
        assert {item.code: item.id for item in resolver.resolve_universe("us_index_etf")} == etfs_before
        assert all(item.instrument_type == "ETF" and item.currency == "USD" for item in sync.load_scope())
        with engine.begin() as conn:
            assert conn.scalar(select(func.count()).select_from(UniverseMember).where(
                UniverseMember.universe_id == sync_id,
            )) == len(required)
            dia_id = conn.scalar(select(Instrument.id).where(Instrument.code == "DIA.US"))
            conn.execute(StockDaily.__table__.insert().values(
                id=1, instrument_id=dia_id, date=date(2026, 9, 22),
                open=100, high=101, low=99, close=100, volume=1000, data_source="test",
            ))
            migration.op = Operations(MigrationContext.configure(conn))
            migration.downgrade()
            assert conn.scalar(select(func.count()).select_from(StockDaily)) == 1
            assert conn.scalar(select(Instrument.id).where(Instrument.code == "DIA.US")) == dia_id
            assert conn.scalar(select(UniverseMember.source).where(
                UniverseMember.universe_id == sync_id, UniverseMember.instrument_id == spy_id,
            )) == "EXISTING"
            migration.upgrade()
        assert {item.code for item in sync.load_scope()} == required
        assert {item.code: item.id for item in resolver.resolve_universe("us_index_etf")} == etfs_before
    finally:
        engine.dispose()
