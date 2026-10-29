from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.universe import Universe, UniverseMember
from finance_analysis.database.repositories.stock import InstrumentRepository
from finance_analysis.stocks.industry_etf_service import StockETFProxyService


def test_etf_and_unsupported_market_do_not_get_stock_proxies():
    repository = Mock()
    service = StockETFProxyService(repository)
    for instrument in [
        SimpleNamespace(market="US", instrument_type="ETF"),
        SimpleNamespace(market="HK", instrument_type="STOCK"),
    ]:
        assert service.resolve(instrument, [dict(code="any", name="行业")])["etf_proxies"] == []
    repository.rotation_etf_names.assert_not_called()


def test_rotation_names_use_pool_membership_not_coarse_types_and_exclude_other_pools_or_disabled_assets():
    engine = create_engine("sqlite://")
    for table in [Instrument.__table__, Universe.__table__, UniverseMember.__table__]:
        table.create(engine)

    class DB:
        @contextmanager
        def get_session(self):
            with Session(engine) as session:
                yield session

    with Session(engine) as session, session.begin():
        pools = [
            Universe(key=key, name=key, market="US", universe_type="STRATEGY", enabled=enabled)
            for key, enabled in [("us_index_etf", True), ("us_macro", True)]
        ]
        session.add_all(pools)
        assets = [
            Instrument(
                code=code,
                native_code=code.split(".")[0],
                name=code,
                market="US",
                instrument_type=kind,
                currency="USD",
                source="TEST",
                listing_status=status,
            )
            for code, kind, status in [
                ("SMH.US", "ETF", "ACTIVE"),
                ("SPY.US", "ETF", "ACTIVE"),
                ("OLD.US", "ETF", "DELISTED"),
                ("XAR.US", "STOCK", "ACTIVE"),
            ]
        ]
        session.add_all(assets)
        session.flush()
        for asset in assets:
            pool = pools[1] if asset.code == "SPY.US" else pools[0]
            session.add(UniverseMember(universe_id=pool.id, instrument_id=asset.id, source="TEST"))
    queries = []
    event.listen(engine, "before_cursor_execute", lambda *args: queries.append(args[2]))
    repository = InstrumentRepository(DB())
    assert repository.rotation_etf_names("US", ["SMH.US", "SPY.US", "OLD.US", "XAR.US", "NVDA.US"]) == {
        "SMH.US": "SMH.US",
        "XAR.US": "XAR.US",
    }
    assert len(queries) == 1
    assert repository.rotation_etf_names("US", []) == {}
    assert len(queries) == 1
    with Session(engine) as session, session.begin():
        pool = session.query(Universe).filter_by(key="us_index_etf").one()
        pool.enabled = False
    assert repository.rotation_etf_names("US", ["SMH.US"]) == {}
