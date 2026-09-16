"""Offline US Macro integration tests: real SQLite repositories and a forbidden remote path."""

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from finance_analysis.database.index_etf import seed_index_etf_universes
from finance_analysis.database.models.stock import Instrument, StockDaily
from finance_analysis.database.models.universe import Universe, UniverseInclude, UniverseMember
from finance_analysis.database.repositories.macro import MacroRepository
from finance_analysis.database.repositories.stock import InstrumentRepository, StockRepository
from finance_analysis.database.repositories.universe import UniverseRepository, UniverseResolver
from finance_analysis.database.us_macro import seed_us_macro
from finance_analysis.integrations.market_data.models import Adjustment, DailyBarsRequest
from finance_analysis.integrations.market_data.normalizer import bars_from_frame
from finance_analysis.integrations.market_data.providers.yfinance import YFinanceProvider, YFINANCE_SYMBOL_OVERRIDES
from finance_analysis.integrations.market_data.registry import ProviderRegistry
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.integrations.market_data.validator import validate_bars
from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.endpoints.macro import get_macro_service
from finance_analysis.interfaces.api.v1.router import router
from finance_analysis.macro.config import MACRO_INSTRUMENTS, RISK_SIGNALS
from finance_analysis.macro.service import MacroService, divide
from finance_analysis.tasks.celery.jobs.market_data_sync.service import MarketDataSyncService


class Database:
    def __init__(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        event.listen(self.engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
        for model in (Instrument, StockDaily, Universe, UniverseMember, UniverseInclude):
            model.__table__.create(self.engine)

    @contextmanager
    def get_session(self):
        with Session(self.engine) as session:
            yield session

    @contextmanager
    def session_scope(self):
        with Session(self.engine) as session, session.begin():
            yield session


@pytest.fixture
def database():
    database = Database()
    with database.engine.begin() as connection:
        seed_us_macro(connection)
    yield database
    database.engine.dispose()


def add_history(database, code, days, values):
    with database.session_scope() as session:
        instrument_id = session.scalar(select(Instrument.id).where(Instrument.code == code))
        next_id = (session.scalar(select(func.max(StockDaily.id))) or 0) + 1
        for offset, (day, value) in enumerate(zip(days, values)):
            session.add(
                StockDaily(
                    id=next_id + offset,
                    instrument_id=instrument_id,
                    date=day,
                    open=value,
                    high=value,
                    low=value,
                    close=value,
                    volume=0,
                    data_source="fixture",
                )
            )


def service(database):
    market = MarketDataService(
        ProviderRegistry(),
        instrument_repository=InstrumentRepository(database),
        stock_repository=StockRepository(database),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Macro attempted remote routing")

    market.router.route_daily = forbidden
    return MacroService(MacroRepository(database), market)


def sessions(count=25):
    return list(pd.bdate_range(end="2026-09-11", periods=count).date)


def test_seed_migration_idempotence_scope_and_etf_isolation(database):
    with database.engine.begin() as connection:
        seed_index_etf_universes(connection)
    resolver = UniverseResolver(UniverseRepository(database))
    before = {item.code: item.id for item in resolver.resolve_universe("us_index_etf")}
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_heads() == ["0055_industry_history"]
    migration = scripts.get_revision("0051_us_macro").module
    with database.engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()
    members = resolver.resolve_universe("us_macro")
    assert {item.code for item in members} == set(MACRO_INSTRUMENTS)
    assert all(
        item.currency == "USD" and item.instrument_type == MACRO_INSTRUMENTS[item.code].instrument_type
        for item in members
    )
    assert {item.code: item.id for item in resolver.resolve_universe("us_index_etf")} == before
    sync = MarketDataSyncService(
        "US", stock_repository=SimpleNamespace(), universe_resolver=resolver, market_data_service=SimpleNamespace()
    )
    assert {item.code for item in sync.load_scope()} == set(MACRO_INSTRUMENTS)
    spy_id = next(item.id for item in members if item.code == "SPY.US")
    assert spy_id == before["SPY.US"]
    add_history(database, "VIX.US", [date(2026, 9, 11)], [18])
    with database.engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()
        assert connection.scalar(select(func.count()).select_from(StockDaily)) == 1
        assert connection.scalar(select(Instrument.id).where(Instrument.code == "SPY.US")) == spy_id
        assert connection.scalar(select(Universe.id).where(Universe.key == "us_macro")) is None
        migration.upgrade()
    assert {item.code: item.id for item in resolver.resolve_universe("us_index_etf")} == before


def test_startup_seed_keeps_macro_include(database):
    # ModelDefinition is unrelated PostgreSQL JSONB metadata; copy its DDL with
    # SQLite JSON types so the real startup seed can run entirely offline.
    from sqlalchemy import JSON, MetaData
    from sqlalchemy.dialects.postgresql import JSONB
    from finance_analysis.database.models.quant import ModelDefinition
    from finance_analysis.database.seed import seed_quant_reference_data

    table = ModelDefinition.__table__.to_metadata(MetaData())
    for column in table.columns:
        if isinstance(column.type, JSONB):
            column.type = JSON()
    table.create(database.engine)
    seed_quant_reference_data(database)
    seed_quant_reference_data(database)
    repository = UniverseRepository(database)
    parent = repository.get_by_key("us_daily_sync")
    assert {item.key for item in repository.list_included_universes(parent.id)} == {
        "us_sp500",
        "us_index_etf",
        "us_macro",
    }
    assert {item.code for item in UniverseResolver(repository).resolve_universe("us_macro")} == set(MACRO_INSTRUMENTS)


@pytest.mark.parametrize("code,ticker", list(YFINANCE_SYMBOL_OVERRIDES.items()) + [("BRK.B.US", "BRK-B")])
def test_index_mapping(code, ticker):
    assert YFinanceProvider.to_yfinance_symbol(code) == ticker


@pytest.mark.parametrize("volume", [None, float("nan"), "absent", 0])
def test_index_missing_volume_only_and_provider_download(monkeypatch, volume):
    row = {"Date": date(2026, 9, 11), "Open": 18, "High": 20, "Low": 17, "Close": 19}
    if volume != "absent":
        row["Volume"] = volume
    frame = pd.DataFrame([row])
    kwargs = dict(provider="yfinance", interval="1d", adjustment="forward")
    bars = bars_from_frame(frame, symbol="VIX.US", instrument_type="INDEX", **kwargs)
    assert len(validate_bars(bars)) == 1 and bars[0].volume == 0
    for code, kind in (("SPY.US", "ETF"), ("AAPL.US", "STOCK")):
        assert bool(bars_from_frame(frame, symbol=code, instrument_type=kind, **kwargs)) == (volume == 0)
    bad = frame.copy()
    bad["Close"] = None
    assert not bars_from_frame(bad, symbol="VIX.US", instrument_type="INDEX", **kwargs)
    provider = YFinanceProvider(max_retries=0)
    calls = []

    def download(symbols, **kwargs):
        calls.append((symbols, kwargs))
        return frame.set_index("Date")

    monkeypatch.setattr(provider, "_download", download)
    result = provider.fetch_daily_bars(
        DailyBarsRequest(
            ("VIX.US",),
            date(2026, 9, 11),
            date(2026, 9, 11),
            Adjustment.FORWARD,
        )
    )
    assert result.data["VIX.US"][0].volume == 0
    assert calls[0][0] == ["^VIX"] and calls[0][1]["auto_adjust"] is True


def test_date_aligned_ratios_zero_denominator():
    days = sessions(4)
    assert divide({days[0]: 2, days[2]: 6, days[3]: 8}, {days[1]: 2, days[2]: 3, days[3]: 0}) == {days[2]: 2}


def test_dashboard_as_of_returns_partial_quality_and_query_budget(database):
    days = sessions()
    add_history(database, "SPY.US", days, list(range(100, 125)))
    add_history(database, "VIX.US", days[:-1], list(range(50, 26, -1)))
    add_history(database, "TLT.US", days[-3:], [90, 91, 92])
    statements = []
    event.listen(database.engine, "before_cursor_execute", lambda c, cur, sql, p, ctx, many: statements.append(sql))
    result = service(database).dashboard(date(2026, 9, 12))
    assert len(statements) == 4 and all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    assert result.trade_date == date(2026, 9, 11)
    spy = next(item for item in result.instruments if item.code == "SPY.US")
    assert spy.close == 124 and spy.ret_1d == pytest.approx(124 / 123 - 1)
    assert spy.ret_5d == pytest.approx(124 / 119 - 1) and spy.ret_20d == pytest.approx(124 / 104 - 1)
    assert spy.trend == "UP"
    assert result.data_quality.expected == 13 and result.data_quality.available == 2
    assert result.data_quality.coverage == pytest.approx(2 / 13)
    assert result.data_quality.stale_symbols == ["VIX.US"]
    assert "UUP.US" in result.data_quality.missing_symbols
    assert result.data_quality.insufficient_history_symbols == ["TLT.US"]
    assert result.data_quality.partial and result.risk_score is None and result.regime is None
    assert result.states.volatility is None
    earlier = service(database).dashboard(days[-3])
    assert earlier.trade_date == days[-3] and earlier.instruments[0].close == 122


def test_chart_modes_and_ratio_alignment(database):
    days = sessions(4)
    add_history(database, "SPY.US", days, [10, 20, 30, 40])
    add_history(database, "SMH.US", [days[0], days[2], days[3]], [20, 90, 160])
    macro = service(database)
    price = macro.series(range="20d", mode="price", symbols=["SMH.US"])
    assert [p.value for p in price.series[0].points] == [20, 90, 160]
    normalized = macro.series(range="20d", mode="normalized", symbols=["SMH.US"])
    assert [p.value for p in normalized.series[0].points] == [100, 450, 800]
    relative = macro.series(range="20d", mode="relative", symbols=["SMH.US"])
    assert [p.value for p in relative.series[0].points] == [100, 150, 200]
    assert [p.date for p in relative.series[0].points] == [days[0], days[2], days[3]]
    ratio = macro.series(range="20d", mode="price", series=["SMH_SPY"])
    assert [p.value for p in ratio.series[0].points] == [2, 3, 4] and ratio.series[0].partial
    ratio_normalized = macro.series(range="20d", series=["SMH_SPY"])
    assert [p.value for p in ratio_normalized.series[0].points] == [100, 150, 200]
    dashboard = macro.dashboard()
    assert next(item for item in dashboard.ratios if item.key == "SMH_SPY").value == 4


def test_windows_ytd_empty_and_stale_outside_chart(database):
    days = sessions(270)
    add_history(database, "SPY.US", days, [100] * len(days))
    add_history(database, "VIX.US", days[:1], [20])
    macro = service(database)
    for count in (20, 60, 120, 250):
        result = macro.series(range=f"{count}d", symbols=["SPY.US", "VIX.US"])
        assert len(result.series[0].points) == count
        assert result.series[1].points == []
        assert result.data_quality.stale_symbols == ["VIX.US"]
        assert "VIX.US" not in result.data_quality.missing_symbols
    ytd = macro.series(range="ytd", symbols=["SPY.US"])
    assert all(point.date.year == 2026 for point in ytd.series[0].points)
    empty = macro.dashboard(date(1999, 1, 1))
    assert empty.trade_date is None and empty.risk_score is None and empty.data_quality.coverage == 0
    assert all(item.close is None for item in empty.instruments)


@pytest.mark.parametrize("direction,expected", [(1, "RISK_ON"), (-1, "RISK_OFF"), (0, "NEUTRAL")])
def test_regime_explained_rules(database, direction, expected):
    days = sessions(21)
    for code in MACRO_INSTRUMENTS:
        sign = -1 if code in {"VIX.US", "TLT.US", "UUP.US"} else 1
        slope = 0 if code in {"LQD.US", "XLP.US"} else 2 if code in {"SMH.US", "IWM.US"} else 1
        add_history(database, code, days, [100 + sign * direction * slope * i for i in range(21)])
    result = service(database).dashboard()
    assert result.regime == expected and result.signal_coverage == 1
    assert result.risk_score == sum(signal.contribution for signal in result.signals)
    assert sum(weight for _, _, weight in RISK_SIGNALS) == 100
    assert not result.data_quality.partial


def test_api_auth_dashboard_series_validation(database):
    add_history(database, "SPY.US", sessions(21), list(range(100, 121)))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_macro_service] = lambda: service(database)
    with TestClient(app) as client:
        assert client.get("/api/v1/macro/dashboard").status_code == 401
        assert client.get("/api/v1/macro/series").status_code == 401
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1)
        response = client.get("/api/v1/macro/dashboard?as_of=2026-09-12")
        assert response.status_code == 200 and response.json()["trade_date"] == "2026-09-11"
        response = client.get("/api/v1/macro/series?symbols=SPY.US&range=20d&mode=normalized")
        assert response.status_code == 200 and response.json()["series"][0]["points"][0]["value"] == 100
        assert client.get("/api/v1/macro/series?series=HYG_LQD").status_code == 200
        for query in (
            "range=3d",
            "mode=foo",
            "symbols=AAPL.US",
            "series=NOPE",
            "benchmark=AAPL.US",
            "mode=relative&series=HYG_LQD",
            "as_of=invalid",
        ):
            assert client.get(f"/api/v1/macro/series?{query}").status_code == 422
        assert client.post("/api/v1/macro/sync").status_code == 404


@pytest.mark.parametrize("count", [20, 21])
@pytest.mark.parametrize(
    "code,state_name",
    [
        ("SPY.US", None),
        ("QQQ.US", None),
        ("VIX.US", "volatility"),
        ("TLT.US", "rates"),
        ("UUP.US", "dollar"),
    ],
)
def test_instrument_signal_requires_21_bars_without_hiding_trend(database, count, code, state_name):
    add_history(database, code, sessions(count), list(range(100, 100 + count)))
    result = service(database).dashboard()
    instrument = next(item for item in result.instruments if item.code == code)
    signal = next(item for item in result.signals if item.key == code)
    assert instrument.trade_date == result.trade_date
    assert instrument.trend == signal.trend == "UP"
    assert (code in result.data_quality.insufficient_history_symbols) == (count == 20)
    if count == 20:
        assert signal.contribution is None
        assert result.signal_coverage == 0
    else:
        assert signal.contribution == (signal.weight if signal.risk_on_trend == "UP" else 0)
        assert result.signal_coverage == signal.weight / 100
    if state_name:
        assert (getattr(result.states, state_name) is None) == (count == 20)


@pytest.mark.parametrize("common_count,stale", [(20, False), (21, False), (21, True)])
def test_ratio_signal_uses_aligned_history_count_and_freshness(database, common_count, stale):
    days = sessions(common_count + 10 + int(stale))
    common_days = days[10:-1] if stale else days[10:]
    hyg_days, lqd_days = days[:5] + common_days, days[5:10] + common_days
    assert len(hyg_days) >= 25 and len(lqd_days) >= 25
    assert len(set(hyg_days) & set(lqd_days)) == common_count
    add_history(database, "HYG.US", hyg_days, list(range(100, 100 + len(hyg_days))))
    add_history(database, "LQD.US", lqd_days, [100] * len(lqd_days))
    if stale:
        add_history(database, "SPY.US", days[-1:], [100])
    result = service(database).dashboard()
    ratio = next(item for item in result.ratios if item.key == "HYG_LQD")
    signal = next(item for item in result.signals if item.key == "HYG_LQD")
    assert ratio.trend == "UP"
    if common_count == 20 or stale:
        assert ratio.partial and ratio.signal is None
        assert signal.contribution is None
        assert result.states.credit is None
        assert result.signal_coverage == 0
    else:
        assert ratio.signal == "RISK_ON" and signal.contribution == 15
        assert result.states.credit == "HEALTHY"
        assert result.signal_coverage == 0.15


@pytest.mark.parametrize(
    "short_symbols,coverage",
    [
        ({"QQQ.US", "VIX.US", "TLT.US", "UUP.US"}, 0.60),
        ({"VIX.US", "TLT.US"}, 0.75),
    ],
)
def test_signal_coverage_and_score_exclude_insufficient_history(database, short_symbols, coverage):
    for code in MACRO_INSTRUMENTS:
        count = 20 if code in short_symbols else 21
        add_history(database, code, sessions(count), list(range(100, 100 + count)))
    result = service(database).dashboard()
    assert set(result.data_quality.insufficient_history_symbols) == short_symbols
    assert result.signal_coverage == pytest.approx(coverage)
    for signal in result.signals:
        if signal.key in short_symbols:
            assert signal.trend == "UP" and signal.contribution is None
    supported = sum(signal.weight for signal in result.signals if signal.contribution is not None)
    assert result.signal_coverage == supported / 100
    if coverage < 0.65:
        assert result.risk_score is None and result.regime is None
    else:
        earned = sum(signal.contribution for signal in result.signals if signal.contribution is not None)
        assert result.risk_score == pytest.approx(earned / supported * 100)
        assert result.regime == "NEUTRAL"
