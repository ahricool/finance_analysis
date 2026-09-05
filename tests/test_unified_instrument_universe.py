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
        repository.upsert_symbols([{"market": "CN", "code": "600519.SH", "name": "贵州茅台股份", "source": "AKSHARE"}])
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
        session.add(UniverseMember(universe_id=index.id, instrument_id=active.id, source="AKSHARE"))
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
        "us_sp500", [{"code": "AAPL.US", "metadata": {}}], "WIKIPEDIA"
    )
    assert stats == MembershipSyncStats(inserted=0, deleted=1, total=1)


def test_reference_data_sync_updates_three_markets_and_five_index_universes():
    class Instruments:
        def upsert_symbols(self, members):
            raise AssertionError("Index membership must not overwrite Instrument Master")

        def existing_codes(self, codes):
            return set(codes)

    class Universes:
        def __init__(self):
            self.keys = []

        def replace_members_with_stats(self, key, members, source):
            self.keys.append((key, source))
            return MembershipSyncStats(inserted=len(members), total=len(members))

    class Provider:
        def fetch_index_members(self, index_code):
            market = "CN" if index_code.isdigit() else "US"
            suffix = ".SH" if market == "CN" else ".US"
            return [{"market": market, "code": f"{index_code}{suffix}", "name": index_code}]

    universes = Universes()
    service = ReferenceDataSyncService(
        instrument_repository=Instruments(),
        universe_repository=universes,
        instrument_primary=object(),
        instrument_fallback=object(),
        index_providers={"AKSHARE": Provider(), "WIKIPEDIA": Provider()},
    )
    service.instrument_sync.sync_instruments_detailed = lambda market: InstrumentSyncResult(
        fetched=10, inserted=2, updated=8, delisted=0, provider="TICKFLOW", fallback_used=False
    )

    result = service.run()

    assert result["instrument_fetched"] == 30
    assert result["universe_count"] == 5
    assert {key for key, _ in universes.keys} == {"cn_csi300", "cn_csi500", "cn_csi1000", "us_sp500", "us_nasdaq100"}


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
