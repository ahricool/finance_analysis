from contextlib import contextmanager
from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from finance_analysis.database.models.stock import Instrument, validate_instrument_code
from finance_analysis.database.models.universe import Universe, UniverseInclude, UniverseMember
from finance_analysis.database.repositories.stock import InstrumentRepository
from finance_analysis.database.repositories.universe import UniverseCycleError, UniverseRepository, UniverseResolver
from finance_analysis.integrations.market_data.instrument_sync import InstrumentSyncService
from finance_analysis.integrations.market_data.models import InstrumentRequest
from finance_analysis.integrations.market_data.providers.tickflow import TickFlowFreeProvider
from finance_analysis.integrations.market_data.service import _DatabaseInstrumentProvider
from finance_analysis.interfaces.api.v1.router import router as api_router


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
        for market, code in (("CN", "600519.SH"), ("CN", "300750.SZ"), ("CN", "920001.BJ"),
                             ("US", "AAPL.US"), ("HK", "700.HK"))
    ]
    assert repository.upsert_symbols(records) == 5
    assert repository.upsert_symbols(
        [
            {
                **records[0],
                "name": "贵州茅台",
                "instrument_type": "ETF",
                "listing_date": date(2001, 8, 27),
                "metadata": {"exchange": "SH"},
            }
        ]
    ) == 1
    assert repository.upsert_symbols(
        [{"market": "CN", "code": "600519.SH", "name": "贵州茅台股份", "source": "AKSHARE"}]
    ) == 1
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
        session.add(UniverseMember(universe_id=index.id, instrument_id=active.id, source="AKSHARE"))
        session.add(UniverseMember(universe_id=strategy.id, instrument_id=manual.id, source="MANUAL"))
        session.add_all([
            UniverseInclude(universe_id=strategy.id, included_universe_id=market.id),
            UniverseInclude(universe_id=strategy.id, included_universe_id=index.id),
        ])
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
        session.add_all([
            UniverseInclude(universe_id=a.id, included_universe_id=b.id),
            UniverseInclude(universe_id=b.id, included_universe_id=a.id),
        ])
    with pytest.raises(UniverseCycleError, match="a -> b -> a"):
        UniverseResolver(UniverseRepository(database)).resolve_universe("a")


def test_instrument_sync_uses_fallback_without_deleting_existing_rows():
    class Primary:
        def fetch_instruments(self, market):
            raise RuntimeError("temporary provider failure")

    class Fallback:
        def fetch_instruments(self, market):
            return [{"market": market, "code": "600519.SH", "name": "贵州茅台"}]

    class Instruments:
        def __init__(self):
            self.records = None
            self.delisted = []

        def upsert_symbols(self, records):
            self.records = records
            return len(records)

        def mark_missing_delisted(self, market, active_codes):
            self.delisted.append((market, set(active_codes)))

    instruments = Instruments()
    service = InstrumentSyncService(
        Primary(), Fallback(), instrument_repository=instruments, universe_repository=object()
    )
    assert service.sync_instruments("CN") == 1
    assert instruments.records[0]["code"] == "600519.SH"
    assert instruments.delisted == []

    service = InstrumentSyncService(
        Fallback(), instrument_repository=instruments, universe_repository=object()
    )
    assert service.sync_instruments("CN") == 1
    assert instruments.delisted == [("CN", {"600519.SH"})]


def test_csi300_500_1000_sync_replaces_current_members_only_after_all_fetches_succeed():
    class Provider:
        def fetch_index_members(self, index_code):
            return [{"code": f"{index_code}.SH", "metadata": {}}]

    class Universes:
        def __init__(self):
            self.calls = []

        def replace_members(self, key, members, source):
            self.calls.append((key, members, source))
            return len(members)

    universes = Universes()
    service = InstrumentSyncService(
        object(), instrument_repository=object(), universe_repository=universes
    )
    assert service.sync_csi_members(Provider()) == {
        "cn_csi300": 1,
        "cn_csi500": 1,
        "cn_csi1000": 1,
    }
    assert [call[0] for call in universes.calls] == ["cn_csi300", "cn_csi500", "cn_csi1000"]
    assert all(call[2] == "AKSHARE" for call in universes.calls)


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
            return []

    client = type("Client", (), {"exchanges": Exchanges()})()
    records = TickFlowFreeProvider(client=client).fetch_instruments("CN")
    assert {item["code"] for item in records} == {"510300.SH", "920001.BJ"}
    bj = next(item for item in records if item["code"] == "920001.BJ")
    assert bj["listing_date"].isoformat() == "2024-01-02"
    assert bj["source"] == "TICKFLOW"
