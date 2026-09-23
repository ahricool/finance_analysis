from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from finance_analysis.database.models.stock import Instrument, validate_instrument_code
from finance_analysis.database.models.universe import Universe, UniverseInclude, UniverseMember
from finance_analysis.database.repositories.stock import InstrumentRepository
from finance_analysis.database.repositories.universe import (
    MembershipSyncStats,
    UniverseCycleError,
    UniverseRepository,
    UniverseResolver,
)
from finance_analysis.integrations.market_data.instrument_sync import InstrumentSyncResult, InstrumentSyncService
from finance_analysis.integrations.market_data.models import InstrumentRequest
from finance_analysis.integrations.market_data.providers.tickflow import TickFlowFreeProvider
from finance_analysis.integrations.market_data.providers.longbridge.market import LongbridgeProvider
from finance_analysis.integrations.market_data.service import _DatabaseInstrumentProvider
from finance_analysis.interfaces.api.v1.router import router as api_router
from finance_analysis.tasks.celery.jobs.reference_data_sync.service import ReferenceDataSyncService


def test_removed_domains_are_absent_from_current_schema_and_api():
    current_tables = set(Instrument.metadata.tables)
    assert current_tables.isdisjoint(
        {
            "portfolio_account",
            "account_cash_balance",
            "position",
            "option_contract",
            "market_data_symbol",
            "quant_universe",
            "quant_universe_member",
        }
    )
    assert not any(route.path.startswith("/api/v1/portfolio") for route in api_router.routes)
    assert set(Instrument.__table__.columns.keys()) == {
        "id",
        "market",
        "code",
        "native_code",
        "name",
        "instrument_type",
        "currency",
        "listing_date",
        "listing_status",
        "source",
        "metadata",
        "created_at",
        "updated_at",
    }


class Database:
    def __init__(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        event.listen(self.engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
        for table in (Instrument.__table__, Universe.__table__, UniverseMember.__table__, UniverseInclude.__table__):
            table.create(self.engine)

    @contextmanager
    def get_session(self):
        with Session(self.engine) as session:
            yield session

    @contextmanager
    def session_scope(self):
        with Session(self.engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise


def test_instrument_validation_and_upsert_support_all_canonical_markets():
    database = Database()
    repository = InstrumentRepository(database)
    records = [
        {"market": market, "code": code, "name": code, "source": "TICKFLOW"}
        for market, code in (
            ("CN", "600519.SH"),
            ("CN", "300750.SZ"),
            ("CN", "920001.BJ"),
            ("US", "AAPL.US"),
            ("HK", "700.HK"),
        )
    ]
    assert repository.upsert_symbols(records) == 5
    assert (
        repository.upsert_symbols(
            [
                {
                    **records[0],
                    "name": "贵州茅台",
                    "instrument_type": "ETF",
                    "listing_date": date(2001, 8, 27),
                    "metadata": {"exchange": "SH"},
                }
            ]
        )
        == 1
    )
    assert (
        repository.upsert_symbols([{"market": "CN", "code": "600519.SH", "name": "贵州茅台股份", "source": "FUYAO"}])
        == 1
    )
    migrated = repository.get_by_code("600519.SH")
    assert migrated.name == "贵州茅台股份"
    assert migrated.instrument_type == "ETF"
    assert migrated.listing_date == date(2001, 8, 27)
    assert migrated.instrument_metadata == {"exchange": "SH"}
    assert migrated.source == "TICKFLOW"
    info = _DatabaseInstrumentProvider(repository).get_instrument_info(InstrumentRequest(symbols=("600519.SH",)))
    assert info.data["600519.SH"].instrument_type == "etf"
    for item in records:
        assert validate_instrument_code(item["market"], item["code"]) == item["code"]


def test_resolver_market_index_strategy_include_dedup_and_manual_member():
    database = Database()
    with database.session_scope() as session:
        active = Instrument(market="CN", code="600519.SH", name="贵州茅台")
        manual = Instrument(market="CN", code="920001.BJ", name="北交所股票")
        etf = Instrument(market="CN", code="510300.SH", name="沪深300ETF", instrument_type="ETF")
        session.add_all([active, manual, etf])
        session.flush()
        market = Universe(key="cn_all_a", name="全部A股", market="CN", universe_type="MARKET")
        index = Universe(key="cn_csi300", name="沪深300", market="CN", universe_type="INDEX")
        strategy = Universe(key="cn_trend", name="A股趋势", market="CN", universe_type="STRATEGY")
        session.add_all([market, index, strategy])
        session.flush()
        session.add(UniverseMember(universe_id=index.id, instrument_id=active.id, source="FUYAO"))
        session.add(UniverseMember(universe_id=strategy.id, instrument_id=manual.id, source="MANUAL"))
        session.add_all(
            [
                UniverseInclude(universe_id=strategy.id, included_universe_id=market.id),
                UniverseInclude(universe_id=strategy.id, included_universe_id=index.id),
            ]
        )
    resolver = UniverseResolver(UniverseRepository(database))
    assert [item.code for item in resolver.resolve_universe("cn_all_a")] == ["600519.SH", "920001.BJ"]
    assert [item.code for item in resolver.resolve_universe("cn_csi300")] == ["600519.SH"]
    assert [item.code for item in resolver.resolve_universe("cn_trend")] == ["600519.SH", "920001.BJ"]


def test_resolver_rejects_include_cycles():
    database = Database()
    with database.session_scope() as session:
        a = Universe(key="a", name="A", market="US", universe_type="STRATEGY")
        b = Universe(key="b", name="B", market="US", universe_type="STRATEGY")
        session.add_all([a, b])
        session.flush()
        session.add_all(
            [
                UniverseInclude(universe_id=a.id, included_universe_id=b.id),
                UniverseInclude(universe_id=b.id, included_universe_id=a.id),
            ]
        )
    with pytest.raises(UniverseCycleError, match="a -> b -> a"):
        UniverseResolver(UniverseRepository(database)).resolve_universe("a")


def test_daily_sync_universes_are_explicit_unions_and_exclude_nasdaq100():
    database = Database()
    with database.session_scope() as session:
        cn_a = Instrument(market="CN", code="600001.SH", name="A")
        cn_b = Instrument(market="CN", code="000002.SZ", name="B")
        us_sp = Instrument(market="US", code="AAPL.US", name="Apple")
        us_ndx = Instrument(market="US", code="NVDA.US", name="NVIDIA")
        session.add_all([cn_a, cn_b, us_sp, us_ndx])
        session.flush()
        universes = {
            key: Universe(key=key, name=key, market=market, universe_type="STRATEGY" if "daily" in key else "INDEX")
            for key, market in (
                ("cn_csi300", "CN"),
                ("cn_csi500", "CN"),
                ("cn_csi1000", "CN"),
                ("us_sp500", "US"),
                ("us_nasdaq100", "US"),
                ("cn_daily_sync", "CN"),
                ("us_daily_sync", "US"),
            )
        }
        session.add_all(universes.values())
        session.flush()
        session.add_all(
            [
                UniverseMember(universe_id=universes["cn_csi300"].id, instrument_id=cn_a.id, source="TEST"),
                UniverseMember(universe_id=universes["cn_csi500"].id, instrument_id=cn_b.id, source="TEST"),
                UniverseMember(universe_id=universes["cn_csi1000"].id, instrument_id=cn_a.id, source="TEST"),
                UniverseMember(universe_id=universes["us_sp500"].id, instrument_id=us_sp.id, source="TEST"),
                UniverseMember(universe_id=universes["us_nasdaq100"].id, instrument_id=us_ndx.id, source="TEST"),
            ]
        )
        for child in ("cn_csi300", "cn_csi500", "cn_csi1000"):
            session.add(
                UniverseInclude(universe_id=universes["cn_daily_sync"].id, included_universe_id=universes[child].id)
            )
        session.add(
            UniverseInclude(universe_id=universes["us_daily_sync"].id, included_universe_id=universes["us_sp500"].id)
        )
    resolver = UniverseResolver(UniverseRepository(database))
    assert {item.code for item in resolver.resolve_universe("cn_daily_sync")} == {"600001.SH", "000002.SZ"}
    assert {item.code for item in resolver.resolve_universe("us_daily_sync")} == {"AAPL.US"}


def test_index_membership_refresh_preserves_current_and_deletes_stale():
    database = Database()
    with database.session_scope() as session:
        first = Instrument(market="US", code="AAPL.US", name="Apple")
        stale = Instrument(market="US", code="OLD.US", name="Old")
        universe = Universe(key="us_sp500", name="S&P 500", market="US", universe_type="INDEX")
        session.add_all([first, stale, universe])
        session.flush()
        session.add_all(
            [
                UniverseMember(universe_id=universe.id, instrument_id=first.id, source="OLD"),
                UniverseMember(universe_id=universe.id, instrument_id=stale.id, source="OLD"),
            ]
        )
    stats = UniverseRepository(database).replace_members_with_stats(
        "us_sp500", [{"code": "AAPL.US", "metadata": {}}], "yfinance"
    )
    assert stats == MembershipSyncStats(inserted=0, deleted=1, total=1)


@pytest.mark.parametrize("us_failure", [None, "request", "empty"])
def test_reference_data_sync_routes_seven_universes_and_preserves_us_on_failure(us_failure):
    class Instruments:
        def upsert_symbols(self, members):
            raise AssertionError("Index membership must not overwrite Instrument Master")

        def existing_codes(self, codes):
            return set(codes)

    class Universes:
        def __init__(self):
            self.keys = []
            self.members = {"us_sp500": ["MSFT.US"], "us_nasdaq100": ["MSFT.US"]}

        def replace_members_with_stats(self, key, members, source):
            assert members, "Never replace a Universe with an empty response"
            self.keys.append((key, source))
            self.members[key] = [member["code"] for member in members]
            return MembershipSyncStats(inserted=len(members), total=len(members))

    requested_indices = []

    class Provider:
        def __init__(self, source):
            self.source = source

        def fetch_index_members(self, index_code):
            requested_indices.append((self.source, index_code))
            if self.source == "WIKIPEDIA":
                if us_failure == "request":
                    raise RuntimeError("Wikipedia request failed")
                if us_failure == "empty":
                    return []
                return [{"market": "US", "code": "AAPL.US", "name": "Apple"}]
            return [{"market": "CN", "code": "600519.SH", "name": "贵州茅台"}]

    universes = Universes()
    service = ReferenceDataSyncService(
        instrument_repository=Instruments(),
        universe_repository=universes,
        instrument_primary=object(),
        instrument_fallback=object(),
        index_providers={"AKSHARE": Provider("AKSHARE"), "WIKIPEDIA": Provider("WIKIPEDIA")},
    )
    service.instrument_sync.sync_instruments_detailed = lambda market: InstrumentSyncResult(
        fetched=10, inserted=2, updated=8, delisted=0, provider="TICKFLOW", fallback_used=False
    )

    result = service.run()

    assert result["instrument_fetched"] == 30
    assert requested_indices == [
        ("AKSHARE", "000300"), ("AKSHARE", "000905"),
        ("AKSHARE", "000852"), ("AKSHARE", "932000"),
        ("WIKIPEDIA", "SP500"), ("WIKIPEDIA", "SP400"), ("WIKIPEDIA", "NASDAQ100"),
    ]
    expected_sources = {
        "cn_csi300": "AKSHARE", "cn_csi500": "AKSHARE",
        "cn_csi1000": "AKSHARE", "cn_csi2000": "AKSHARE",
    }
    if us_failure:
        assert result["universe_count"] == 4
        assert result["sync_status"] == "partial"
        assert set(result["failed_universes"]) == {"us_sp500", "us_sp400", "us_nasdaq100"}
        assert universes.members["us_sp500"] == universes.members["us_nasdaq100"] == ["MSFT.US"]
    else:
        assert result["universe_count"] == 7
        assert result["sync_status"] == "success"
        assert result["failed_universes"] == {}
        expected_sources.update(us_sp500="WIKIPEDIA", us_sp400="WIKIPEDIA", us_nasdaq100="WIKIPEDIA")
        assert universes.members["us_sp500"] == universes.members["us_nasdaq100"] == ["AAPL.US"]
    assert dict(universes.keys) == expected_sources
    for key, source in expected_sources.items():
        assert result["provider"][f"universe:{key}"] == source


def test_instrument_sync_uses_fallback_without_deleting_existing_rows():
    class Primary:
        def fetch_instruments(self, market):
            raise RuntimeError("temporary provider failure")

    class Fallback:
        def fetch_instruments(self, market):
            return [
                {"market": market, "code": "600519.SH", "name": "贵州茅台"},
                {"market": market, "code": "000001.SZ", "name": "Fallback name", "source": "LONGBRIDGE"},
            ]

    class Instruments:
        def __init__(self):
            self.records = None
            self.delisted = []

        def upsert_symbols(self, records):
            self.records = records
            return len(records)

        def existing_codes(self, codes):
            return {"000001.SZ"}

        def mark_missing_delisted(self, market, active_codes):
            self.delisted.append((market, set(active_codes)))

    instruments = Instruments()
    service = InstrumentSyncService(Primary(), Fallback(), instrument_repository=instruments)
    result = service.sync_instruments_detailed("CN")
    assert (result.fetched, result.inserted, result.updated, result.delisted) == (2, 1, 0, 0)
    assert result.fallback_used is True
    assert instruments.records == [{"market": "CN", "code": "600519.SH", "name": "贵州茅台"}]
    assert instruments.delisted == []

    service = InstrumentSyncService(Fallback(), instrument_repository=instruments)
    assert service.sync_instruments("CN") == 2
    assert instruments.delisted == [("CN", {"600519.SH", "000001.SZ"})]


@pytest.mark.parametrize("kind", ["ETF", "INDEX"])
def test_missing_members_use_typed_security_metadata_without_overwriting_existing(kind):
    writes = []
    instruments = SimpleNamespace(
        existing_codes=lambda codes: {"AAPL.US"},
        upsert_symbols=lambda records: writes.extend(records),
    )
    info = SimpleNamespace(
        instrument_type=kind,
        market=SimpleNamespace(value="US"),
        name="Provider name",
        currency="USD",
        provider="tickflow",
    )
    primary = SimpleNamespace(get_instrument_info=lambda request: SimpleNamespace(data={"SPY.US": info}))
    service = InstrumentSyncService(primary, instrument_repository=instruments)
    service.ensure_instruments({"AAPL.US", "SPY.US"})
    assert writes == [
        {
            "market": "US",
            "code": "SPY.US",
            "native_code": "SPY",
            "name": "Provider name",
            "instrument_type": kind,
            "currency": "USD",
            "source": "TICKFLOW",
        }
    ]
    default = InstrumentSyncService(instrument_repository=instruments)
    assert isinstance(default.fallback, LongbridgeProvider)
    assert LongbridgeProvider._security_type(SimpleNamespace()) is None


def test_tickflow_directory_filters_products_and_supports_beijing_exchange():
    class Exchanges:
        def get_instruments(self, exchange):
            if exchange == "BJ":
                return [
                    {
                        "symbol": "920001.BJ",
                        "name": "北交所股票",
                        "type": "stock",
                        "ext": {"listing_date": "2024-01-02"},
                    },
                    {"symbol": "123001.BJ", "name": "债券", "type": "bond"},
                ]
            if exchange == "SH":
                return [{"symbol": "510300.SH", "name": "沪深300ETF", "type": "etf"}]
            return [{"symbol": "000001.SZ", "name": "平安银行", "type": "stock"}]

    client = type("Client", (), {"exchanges": Exchanges()})()
    records = TickFlowFreeProvider(client=client).fetch_instruments("CN")
    assert {item["code"] for item in records} == {"000001.SZ", "510300.SH", "920001.BJ"}
    bj = next(item for item in records if item["code"] == "920001.BJ")
    assert bj["listing_date"].isoformat() == "2024-01-02"
    assert bj["source"] == "TICKFLOW"


@pytest.mark.parametrize("existing_pool", [False, True])
def test_index_etf_migration_preserves_members_fk_metadata_and_final_includes(existing_pool):
    import importlib.util
    from finance_analysis.core.paths import PROJECT_ROOT
    from finance_analysis.database.index_etf import INDEX_ETF_MEMBERS, seed_index_etf_universes
    from finance_analysis.etf_rotation.universe import get_etf_universe
    from sqlalchemy import select, text

    database = Database()
    spec = importlib.util.spec_from_file_location(
        "daily_migration", PROJECT_ROOT / "alembic/versions/0041_index_etf_csi2000.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "0041_index_etf_csi2000"
    assert migration.down_revision == "0040_daily_sync_universes"
    expected = {}
    with database.session_scope() as session:
        for key in (
            "cn_all_a",
            "cn_csi300",
            "cn_csi500",
            "cn_csi1000",
            "cn_trend",
            "us_trend",
            "us_sp500",
            "cn_daily_sync",
            "us_daily_sync",
        ):
            session.add(Universe(key=key, name=key, market=key[:2].upper(), universe_type="STRATEGY"))
        session.flush()
        ids = dict(session.execute(select(Universe.key, Universe.id)).all())
        session.add(UniverseInclude(universe_id=ids["cn_trend"], included_universe_id=ids["cn_all_a"]))
        for i, key in enumerate(("cn_csi300", "cn_csi500", "cn_csi1000")):
            instrument = Instrument(market="CN", code=f"60000{i}.SH", name=key)
            session.add(instrument)
            session.flush()
            session.add(UniverseMember(universe_id=ids[key], instrument_id=instrument.id, source="TEST"))
        if not existing_pool:
            session.add(Instrument(market="CN", code="588000.SH", name="Existing name", source="TICKFLOW"))
            for market in ("CN", "US"):
                session.add(
                    Universe(key=f"{market.lower()}_etf_rotation", name=market, market=market, universe_type="STRATEGY")
                )
        if existing_pool:
            for market, members in INDEX_ETF_MEMBERS.items():
                universe = Universe(
                    key=f"{market.lower()}_etf_rotation", name=market, market=market, universe_type="STRATEGY"
                )
                session.add(universe)
                session.flush()
                expected[market] = {}
                for code, name, category, theme, risk_group in members:
                    instrument = Instrument(market=market, code=code, name=name, instrument_type="STOCK")
                    session.add(instrument)
                    session.flush()
                    metadata = dict(category=category, theme=theme, risk_group=risk_group, custom="preserve")
                    session.add(
                        UniverseMember(
                            universe_id=universe.id,
                            instrument_id=instrument.id,
                            source="OLD_POOL",
                            member_metadata=metadata,
                        )
                    )
                    expected[market][code] = (instrument.id, metadata)
    from alembic import command
    from alembic.config import Config

    with database.engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0040_daily_sync_universes')"))
        connection.execute(text("CREATE TABLE signal (id INTEGER PRIMARY KEY)"))
    config = Config()
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.attributes["connection"] = database.engine
    # This fixture contains only security-master tables; stop at its migration boundary.
    command.upgrade(config, "0042_merge_reference_heads")
    with database.engine.begin() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0042_merge_reference_heads"
        )
        from sqlalchemy import inspect

        assert "signal" not in inspect(connection).get_table_names()
        seed_index_etf_universes(connection)  # idempotent after migration
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        pairs = set(connection.execute(text("""
            SELECT p.key, c.key FROM universe_include i
            JOIN universe p ON p.id=i.universe_id JOIN universe c ON c.id=i.included_universe_id
        """)).all())
        assert pairs == set(migration.INCLUDES)
    repository = UniverseRepository(database)
    for market, members in INDEX_ETF_MEMBERS.items():
        assert repository.get_by_key(f"{market.lower()}_etf_rotation") is None
        universe = repository.get_by_key(f"{market.lower()}_index_etf")
        assert universe.market == market and universe.universe_type == "STRATEGY"
        actual = {member.code: member for member in get_etf_universe(market, repository)}
        assert set(actual) == {item[0] for item in members}
        for code, _, category, theme, risk_group in members:
            assert (actual[code].category, actual[code].theme, actual[code].risk_group) == (category, theme, risk_group)
        assert all(member.instrument.instrument_type == "ETF" for member in repository.list_members(universe.id))
        if not existing_pool and market == "CN":
            existing = next(member.instrument for member in repository.list_members(universe.id)
                            if member.instrument.code == "588000.SH")
            assert (existing.name, existing.source) == ("Existing name", "TICKFLOW")
        if existing_pool:
            for member in repository.list_members(universe.id):
                assert (member.instrument_id, member.member_metadata) == expected[market][member.instrument.code]
                assert member.source == "OLD_POOL"
    csi2000_id = repository.get_by_key("cn_csi2000").id
    with database.session_scope() as session:
        instrument = Instrument(market="CN", code="600009.SH", name="CSI2000 only")
        session.add(instrument)
        session.flush()
        session.add(UniverseMember(universe_id=csi2000_id, instrument_id=instrument.id, source="FUYAO"))
    resolver = UniverseResolver(repository)
    assert {item.code for item in resolver.resolve_universe("cn_trend")} == {
        "600000.SH",
        "600001.SH",
        "600002.SH",
        "600009.SH",
    }
    assert {item.code for item in resolver.resolve_universe("cn_daily_sync")} == {
        "600000.SH",
        "600001.SH",
        "600002.SH",
        *[item[0] for item in INDEX_ETF_MEMBERS["CN"]],
    }
    assert {item.code for item in resolver.resolve_universe("us_daily_sync")} == {
        item[0] for item in INDEX_ETF_MEMBERS["US"]
    }


def test_us_trend_migration_union_memberships_and_atomic_replacement(monkeypatch):
    import importlib.util
    from sqlalchemy import select
    from finance_analysis.core.paths import PROJECT_ROOT
    from finance_analysis.trend_following.universe import get_universe

    database = Database()
    with database.session_scope() as session:
        for key in ("us_sp500", "us_nasdaq100", "us_trend", "us_daily_sync", "us_macro", "us_index_etf"):
            session.add(Universe(key=key, name=key, market="US", universe_type="INDEX"))
        session.flush()
        ids = dict(session.execute(select(Universe.key, Universe.id)).all())
        for parent, child in (("us_trend", "us_sp500"), ("us_daily_sync", "us_sp500"),
                              ("us_daily_sync", "us_macro"), ("us_daily_sync", "us_index_etf")):
            session.add(UniverseInclude(universe_id=ids[parent], included_universe_id=ids[child]))
    spec = importlib.util.spec_from_file_location(
        "us_trend_migration", PROJECT_ROOT / "alembic/versions/0057_us_trend_universe.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0056_market_sentiment"
    with database.engine.begin() as connection:
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        migration.upgrade()
        migration.upgrade()  # Repeating the data migration preserves existing relationships.
    instruments = InstrumentRepository(database)
    codes = ["SPONLY.US", "MIDONLY.US", "NDXONLY.US", "AAPL.US"]
    instruments.upsert_symbols([{"code": code, "market": "US", "name": code} for code in codes])
    repository = UniverseRepository(database)
    for key, members in (
        ("us_sp500", ["SPONLY.US", "AAPL.US", "aapl.us"]),
        ("us_sp400", ["MIDONLY.US"]),
        ("us_nasdaq100", ["NDXONLY.US", "AAPL.US"]),
    ):
        repository.replace_members(key, [{"code": code} for code in members], "WIKIPEDIA")
    resolver = UniverseResolver(repository)
    assert [item.code for item in get_universe("US", resolver)] == sorted(codes)
    assert {item.code for item in resolver.resolve_universe("us_daily_sync")} == set(codes)
    assert {item.key for item in repository.list_included_universes(ids["us_daily_sync"])} == {
        "us_sp500", "us_sp400", "us_nasdaq100", "us_macro", "us_index_etf",
    }
    for key in ("us_sp500", "us_nasdaq100"):
        assert "AAPL.US" in {item.code for item in resolver.resolve_universe(key)}
    with pytest.raises(ValueError, match="not registered"):
        repository.replace_members("us_sp400", [{"code": "UNKNOWN.US"}], "WIKIPEDIA")
    assert {item.code for item in resolver.resolve_universe("us_sp400")} == {"MIDONLY.US"}
    stats = repository.replace_members_with_stats("us_sp500", [{"code": "SPONLY.US"}], "WIKIPEDIA")
    assert stats.deleted == 1
    assert "AAPL.US" in {item.code for item in resolver.resolve_universe("us_nasdaq100")}
    assert [item.code for item in get_universe("US", resolver)] == sorted(codes)


@pytest.mark.parametrize("setup", ["seed", "migration", "migration_old_pr"])
def test_daily_trend_and_market_structure_scopes_are_independent(setup, monkeypatch):
    import importlib.util
    from sqlalchemy import JSON, MetaData, select
    from sqlalchemy.dialects.postgresql import JSONB
    from finance_analysis.core.paths import PROJECT_ROOT
    from finance_analysis.database.models.quant import ModelDefinition
    from finance_analysis.database.seed import seed_quant_reference_data
    from finance_analysis.market_structure.universe import get_universe_codes
    from finance_analysis.tasks.celery.jobs.market_data_sync.service import MarketDataSyncService

    expected = {
        "us_trend": {"us_sp500", "us_sp400", "us_nasdaq100"},
        "us_daily_sync": {"us_sp500", "us_sp400", "us_nasdaq100", "us_index_etf", "us_macro"},
        "us_market_structure": {"us_sp500"},
        "cn_trend": {"cn_csi300", "cn_csi500", "cn_csi1000", "cn_csi2000"},
        "cn_daily_sync": {"cn_csi300", "cn_csi500", "cn_csi1000", "cn_csi2000", "cn_index_etf"},
        "cn_market_structure": {"cn_csi300", "cn_csi500", "cn_csi1000"},
    }
    database = Database()
    if setup == "seed":
        table = ModelDefinition.__table__.to_metadata(MetaData())
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
        table.create(database.engine)
        seed_quant_reference_data(database)
        seed_quant_reference_data(database)
    else:
        old = {
            "us_trend": {"us_sp500"},
            "us_daily_sync": {"us_sp500", "us_index_etf", "us_macro"},
            "cn_trend": expected["cn_trend"],
            "cn_daily_sync": expected["cn_daily_sync"] - {"cn_csi2000"},
        }
        if setup == "migration_old_pr":
            old["us_daily_sync"] = {"us_trend", "us_index_etf", "us_macro"}
            old["us_trend"] = expected["us_trend"]
        keys = set(old) | {child for children in old.values() for child in children} | {"us_nasdaq100"}
        with database.session_scope() as session:
            for key in keys:
                session.add(Universe(key=key, name=key, market=key[:2].upper(),
                                     universe_type="STRATEGY" if key in old else "INDEX"))
            session.flush()
            ids = dict(session.execute(select(Universe.key, Universe.id)).all())
            for parent, children in old.items():
                for child in children:
                    session.add(UniverseInclude(universe_id=ids[parent], included_universe_id=ids[child]))
        spec = importlib.util.spec_from_file_location(
            "scope_migration", PROJECT_ROOT / "alembic/versions/0057_us_trend_universe.py"
        )
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with database.engine.begin() as connection:
            monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
            migration.upgrade()
            migration.upgrade()
    repository = UniverseRepository(database)
    for parent, children in expected.items():
        row = repository.get_by_key(parent)
        assert row.universe_type == "STRATEGY"
        assert {item.key for item in repository.list_included_universes(row.id)} == children
    resolver = UniverseResolver(repository)
    instruments = InstrumentRepository(database)
    leaves = sorted({child for children in expected.values() for child in children})
    codes = {}
    for i, key in enumerate(leaves):
        market = key[:2].upper()
        code = f"{600000 + i}.SH" if market == "CN" else f"TEST{i}.US"
        codes[key] = code
        kind = "ETF" if key.endswith(("etf", "macro")) else "STOCK"
        instruments.upsert_symbols([{"code": code, "market": market, "name": code, "instrument_type": kind}])
        repository.replace_members(key, [{"code": code}], "TEST")
    for market in ("CN", "US"):
        prefix = market.lower()
        assert get_universe_codes(market, resolver) == {codes[key] for key in expected[f"{prefix}_market_structure"]}
        sync = object.__new__(MarketDataSyncService)
        sync.market, sync.universe_resolver = market, resolver
        sync_codes = {codes[key] for key in expected[f"{prefix}_daily_sync"]}
        if setup == "seed" and market == "US":
            from finance_analysis.market_review.us_postmarket_symbols import (
                US_POSTMARKET_BENCHMARKS, US_POSTMARKET_SECTOR_ETFS,
            )

            sync_codes |= set(US_POSTMARKET_BENCHMARKS) | set(US_POSTMARKET_SECTOR_ETFS)
        assert {item.code for item in sync.load_scope()} == sync_codes
        assert {item.code for item in resolver.resolve_universe(f"{prefix}_trend")} == {
            codes[key] for key in expected[f"{prefix}_trend"]
        }


@pytest.mark.parametrize(
    "memberships, expected",
    [
        ([("one", "INDEX", True)], ["one"]),
        ([("one", "INDEX", True), ("two", "INDEX", True)], ["one", "two"]),
        ([("strategy", "STRATEGY", True)], []),
        ([("disabled", "INDEX", False)], []),
        ([("market", "MARKET", True)], []),
        ([], []),
    ],
)
def test_index_memberships_use_one_join_and_only_enabled_indices(memberships, expected):
    database = Database()
    with database.session_scope() as session:
        instrument = Instrument(code="NVDA.US", market="US", name="NVIDIA")
        session.add(instrument)
        session.flush()
        for key, kind, enabled in memberships:
            universe = Universe(key=key, name=key, market="US", universe_type=kind, enabled=enabled)
            session.add(universe)
            session.flush()
            session.add(UniverseMember(universe_id=universe.id, instrument_id=instrument.id, source="WIKIPEDIA"))
    queries = []
    event.listen(database.engine, "before_cursor_execute", lambda conn, cursor, statement, *args: queries.append(statement))
    result = UniverseRepository(database).list_index_memberships("NVDA.US")
    assert result == [{"key": key, "name": key, "source": "WIKIPEDIA"} for key in expected]
    assert len(queries) == 1
    assert "JOIN universe_member" in queries[0] and "JOIN universe" in queries[0]
    database.engine.dispose()
