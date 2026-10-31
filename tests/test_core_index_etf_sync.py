"""Core ETF migration/seed coverage using real repositories and isolated databases."""

from contextlib import contextmanager
from datetime import date
from io import StringIO
import os
from types import SimpleNamespace
from uuid import uuid4

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import JSON, MetaData, create_engine, event, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from finance_analysis.database.core_index_etf import CORE_INDEX_ETFS, MEMBER_SOURCE, seed_core_index_etfs
from finance_analysis.database.index_etf import seed_index_etf_universes
from finance_analysis.database.models.quant import ModelDefinition
from finance_analysis.database.models.stock import Instrument, StockDaily
from finance_analysis.database.models.universe import Universe, UniverseInclude, UniverseMember
from finance_analysis.database.repositories.universe import UniverseRepository, UniverseResolver
from finance_analysis.stock_strategies.inputs import BENCHMARKS
from finance_analysis.tasks.celery.jobs.market_data_sync.service import MarketDataSyncService


@pytest.fixture(params=["sqlite", "postgres"])
def database(request):
    admin = schema = None
    if request.param == "postgres":
        url = os.getenv("CORE_INDEX_ETF_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("Requires an explicitly isolated CORE_INDEX_ETF_TEST_POSTGRES_URL")
        schema = "core_etf_test_" + uuid4().hex
        admin = create_engine(url)
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine("sqlite://")
        event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    for model in (Instrument, StockDaily, Universe, UniverseMember, UniverseInclude):
        model.__table__.create(engine)

    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session

    @contextmanager
    def session_scope():
        with Session(engine) as session, session.begin():
            yield session

    try:
        yield SimpleNamespace(engine=engine, get_session=get_session, session_scope=session_scope)
    finally:
        engine.dispose()
        if admin:
            with admin.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def sync_scope(database, market):
    return MarketDataSyncService(
        market, universe_resolver=UniverseResolver(UniverseRepository(database)),
        stock_repository=SimpleNamespace(), market_data_service=SimpleNamespace(),
    ).load_scope()


def test_fresh_seed_is_idempotent_and_all_core_etfs_reach_daily_sync(database):
    with database.engine.begin() as conn:
        seed_core_index_etfs(conn)
        seed_core_index_etfs(conn)
    for market, members in CORE_INDEX_ETFS.items():
        resolved = sync_scope(database, market)
        assert {i.code for i in resolved} == set(members)
        assert BENCHMARKS[market] in members
        assert all(i.market == market and i.instrument_type == "ETF" for i in resolved)
        assert all(i.currency == ("CNY" if market == "CN" else "USD") for i in resolved)
    with database.engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(UniverseMember)) == sum(map(len, CORE_INDEX_ETFS.values()))
        assert conn.scalar(select(func.count()).select_from(StockDaily)) == 0
        assert conn.scalar(select(func.count()).select_from(UniverseInclude)) == 0


def test_migration_preserves_existing_identity_memberships_and_history(database):
    with database.engine.begin() as conn:
        seed_index_etf_universes(conn)
        conn.execute(Universe.__table__.insert().values(
            key="cn_daily_sync", name="existing sync", market="CN", universe_type="STRATEGY", config={"keep": True},
        ))
        universe_id = conn.scalar(select(Universe.id).where(Universe.key == "cn_daily_sync"))
        # Legacy identities may still be classified STOCK; the explicit ETF list corrects only the type.
        conn.execute(Instrument.__table__.insert().values(
            code="510300.SH", native_code="510300", market="CN", name="keep name", instrument_type="STOCK",
            currency="CNY", listing_status="ACTIVE", source="EXISTING", metadata={"keep": True},
        ))
        instrument_id = conn.scalar(select(Instrument.id).where(Instrument.code == "510300.SH"))
        conn.execute(UniverseMember.__table__.insert().values(
            universe_id=universe_id, instrument_id=instrument_id, source="EXISTING", metadata={"keep": True},
        ))
        conn.execute(StockDaily.__table__.insert().values(
            id=1, instrument_id=instrument_id, date=date(2026, 9, 11),
            open=100, high=101, low=99, close=100, volume=1000, data_source="fixture",
        ))
    resolver = UniverseResolver(UniverseRepository(database))
    before = {m: {i.code: i.id for i in resolver.resolve_universe(f"{m.lower()}_index_etf")} for m in ("CN", "US")}
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_heads() == ["0088_holdings_review"]
    migration = scripts.get_revision("0077_core_index_etf_sync").module
    assert migration.down_revision == "0076_stock_strategies"
    with database.engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        migration.upgrade()
        row = conn.execute(select(Instrument.__table__).where(Instrument.code == "510300.SH")).mappings().one()
        assert (row["id"], row["name"], row["source"], row["metadata"], row["instrument_type"]) == (
            instrument_id, "keep name", "EXISTING", {"keep": True}, "ETF",
        )
        assert conn.scalar(select(Universe.config).where(Universe.id == universe_id)) == {"keep": True}
        assert conn.scalar(select(UniverseMember.member_metadata).where(
            UniverseMember.universe_id == universe_id, UniverseMember.instrument_id == instrument_id,
        )) == {"keep": True}
        migration.downgrade()
        assert conn.scalar(select(func.count()).select_from(UniverseMember).where(
            UniverseMember.source == MEMBER_SOURCE,
        )) == 0
        assert conn.scalar(select(UniverseMember.source).where(
            UniverseMember.universe_id == universe_id, UniverseMember.instrument_id == instrument_id,
        )) == "EXISTING"
        assert conn.scalar(select(StockDaily.close)) == 100
        assert conn.scalar(select(Instrument.id).where(Instrument.code == "510300.SH")) == instrument_id
        migration.upgrade()
    for market in ("CN", "US"):
        assert {i.code for i in sync_scope(database, market)} == set(CORE_INDEX_ETFS[market])
        assert {i.code: i.id for i in resolver.resolve_universe(f"{market.lower()}_index_etf")} == before[market]


def test_startup_seed_restores_core_sync_memberships_without_expanding_strategy_pools(database):
    from finance_analysis.database.seed import seed_quant_reference_data

    table = ModelDefinition.__table__.to_metadata(MetaData())
    if database.engine.dialect.name == "sqlite":
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    table.create(database.engine)
    with database.engine.begin() as conn:
        seed_index_etf_universes(conn)
    resolver = UniverseResolver(UniverseRepository(database))
    before = {m: {i.code for i in resolver.resolve_universe(f"{m.lower()}_index_etf")} for m in ("CN", "US")}
    seed_quant_reference_data(database)
    with database.engine.begin() as conn:
        conn.execute(UniverseMember.__table__.delete().where(UniverseMember.source == MEMBER_SOURCE))
    seed_quant_reference_data(database)
    for market in ("CN", "US"):
        assert set(CORE_INDEX_ETFS[market]).issubset({i.code for i in sync_scope(database, market)})
        assert {i.code for i in resolver.resolve_universe(f"{market.lower()}_index_etf")} == before[market]
        assert not resolver.resolve_universe(f"{market.lower()}_trend")


def test_migration_renders_complete_offline_postgresql_sql():
    output = StringIO()
    migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("0077_core_index_etf_sync").module
    context = MigrationContext.configure(dialect_name="postgresql", opts={
        "as_sql": True, "literal_binds": True, "output_buffer": output,
    })
    migration.op = Operations(context)
    migration.upgrade()
    sql = output.getvalue()
    # Rendered scripts must also provide the NOT NULL timestamps; Python defaults render as NULL offline.
    assert "NULL" not in sql
    assert "INSERT INTO universe_member" in sql
    for members in CORE_INDEX_ETFS.values():
        assert all(code in sql for code in members)
