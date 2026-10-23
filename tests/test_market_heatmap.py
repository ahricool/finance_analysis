"""Offline contracts for heatmap data, atomic publication, and cached-only API reads."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.repositories.stock import InstrumentRepository
from finance_analysis.integrations.market_data.models import BatchQuoteResult, Market, MarketQuote
from finance_analysis.integrations.market_data.providers.easyquotation import quote_from_tencent_row
from finance_analysis.integrations.market_data.providers.yfinance import YFinanceProvider
from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.endpoints import market_heatmap as endpoint
from finance_analysis.market_heatmap.service import HeatmapService

NOW = datetime(2026, 10, 23, 2, tzinfo=timezone.utc)


def instrument(code, kind="STOCK", metadata=None):
    return SimpleNamespace(
        code=code,
        name=code,
        instrument_type=kind,
        listing_status="ACTIVE",
        currency="CNY" if code.endswith(".SH") else "USD",
        instrument_metadata=metadata or {},
    )


def quote(code, cap=20e9, change=1):
    market = Market.CN if code.endswith(".SH") else Market.US
    return MarketQuote(
        code,
        market,
        "test",
        "CNY" if market == Market.CN else "USD",
        name=code,
        price=10,
        total_mv=cap,
        change_pct=change,
        quote_time=NOW,
    )


class Cache:
    def __init__(self):
        self.value = None

    def read(self, market):
        return self.value

    def write(self, market, value):
        self.value = value


def test_cn_filters_and_counts_each_stock_once_without_inventing_classification():
    codes = ["600001.SH", "600002.SH", "600003.SH", "510300.SH"]
    snapshots = BatchQuoteResult(data={code: quote(code) for code in codes})
    snapshots.data[codes[2]] = quote(codes[2], cap=1e9)
    cache = Cache()
    service = HeatmapService(
        market_data=Mock(get_market_snapshot=Mock(return_value=snapshots)),
        cache=cache,
        instruments=Mock(
            get_by_codes=Mock(return_value={c: instrument(c, "ETF" if c == codes[3] else "STOCK") for c in codes})
        ),
        industries=Mock(
            reference_data=Mock(
                return_value=(
                    [
                        {"thscode": "broad", "name": "银行", "members_observed_at": NOW},
                        {"thscode": "narrow", "name": "股份制银行", "members_observed_at": NOW},
                    ],
                    {"broad": [{"thscode": codes[0]}, {"thscode": "OTHER.SH"}], "narrow": [{"thscode": codes[0]}]},
                )
            )
        ),
    )
    service.refresh("CN")
    assert len(cache.value["items"]) == 2
    assert cache.value["items"][0]["group_name"] == "银行"
    assert cache.value["unclassified_count"] == 1
    assert cache.value["excluded_count"] == 2
    service.market_data.get_market_snapshot.assert_called_once_with(
        "CN",
        providers=["easyquotation"],
        min_market_cap=10e9,
    )


def test_us_uses_persisted_sector_and_keeps_missing_change_gray():
    cache = Cache()
    code = "AAPL.US"
    service = HeatmapService(
        market_data=Mock(
            get_market_snapshot=Mock(return_value=BatchQuoteResult(data={code: quote(code, change=float("nan"))}))
        ),
        instruments=Mock(
            get_by_codes=Mock(
                return_value={
                    code: instrument(
                        code,
                        metadata={
                            "classification": {
                                "sector": "Technology",
                                "industry": "Consumer Electronics",
                                "observed_at": NOW.isoformat(),
                            }
                        },
                    )
                }
            )
        ),
        cache=cache,
    )
    service.refresh("US")
    assert cache.value["items"][0]["group_name"] == "科技"
    assert cache.value["items"][0]["change_pct"] is None
    assert cache.value["classification_observed_at"] == NOW.isoformat()


def test_failed_or_collapsed_generation_preserves_previous_snapshot():
    cache = Cache()
    cache.value = {"items": [{}] * 10}
    data = Mock(get_market_snapshot=Mock(return_value=BatchQuoteResult(failed_symbols={"US": "failed"})))
    service = HeatmapService(market_data=data, cache=cache, instruments=Mock())
    with pytest.raises(ValueError, match="unavailable"):
        service.refresh("US")
    data.get_market_snapshot.return_value = BatchQuoteResult(data={"AAPL.US": quote("AAPL.US")})
    service.instruments.get_by_codes.return_value = {"AAPL.US": instrument("AAPL.US")}
    with pytest.raises(ValueError, match="coverage dropped"):
        service.refresh("US")
    assert len(cache.value["items"]) == 10


def test_tencent_market_caps_convert_from_hundred_million_to_cny():
    row = quote_from_tencent_row("sh600519", {"now": 100, "总市值": 123.45, "流通市值": 100})
    assert row.total_mv == 12_345_000_000
    assert row.circ_mv == 10_000_000_000


@pytest.mark.parametrize("yahoo,canonical", [("BRK-B", "BRK.B.US"), ("BF-B", "BF.B.US"), ("AAPL", "AAPL.US")])
def test_yahoo_class_shares_match_canonical_instruments(yahoo, canonical):
    assert YFinanceProvider.from_yfinance_symbol(yahoo) == canonical


def test_bulk_classification_carries_query_sector_and_industry_and_fails_atomically(monkeypatch):
    import yfinance as yf

    class Query:
        valid_values = {"industry": {"Technology": ["Consumer Electronics", "Semiconductors"]}}

        def __init__(self, operator, operands):
            self.operands = operands

    monkeypatch.setattr(yf, "EquityQuery", Query)
    provider = YFinanceProvider()
    calls = 0

    def fetch(query):
        nonlocal calls
        calls += 1
        industry = query.operands[1].operands[1]
        return [{"symbol": "AAPL" if industry == "Consumer Electronics" else "NVDA", "quoteType": "EQUITY"}]

    monkeypatch.setattr(provider, "_screen_rows", fetch)
    rows = provider.fetch_stock_classifications(Market.US)
    assert calls == 2
    assert rows["AAPL.US"] == {"sector": "Technology", "industry": "Consumer Electronics", "source": "yfinance"}
    monkeypatch.setattr(
        provider,
        "_screen_rows",
        Mock(
            side_effect=[
                fetch(Query("AND", [None, Query("EQ", [None, "Consumer Electronics"])])),
                ValueError("missing page"),
            ]
        ),
    )
    with pytest.raises(ValueError, match="missing page"):
        provider.fetch_stock_classifications(Market.US)


def test_weekly_sync_failure_does_not_publish_metadata():
    from finance_analysis.stocks.classification_sync import USClassificationSyncService

    repository = Mock()
    sync = USClassificationSyncService(
        repository, Mock(get_stock_classifications=Mock(side_effect=ValueError("failed")))
    )
    with pytest.raises(ValueError):
        sync.run()
    repository.save_us_classifications.assert_not_called()


def test_refresh_cache_uses_single_atomic_set_and_valid_json():
    from finance_analysis.market_heatmap.cache import HeatmapCache

    redis = Mock()
    cache = HeatmapCache(redis)
    cache.write("US", {"items": [1]})
    redis.set.assert_called_once_with("market_heatmap:v1:US", '{"items": [1]}', ex=604800)
    with pytest.raises(ValueError):
        cache.write("US", {"invalid": float("nan")})
    assert redis.set.call_count == 1


def test_yahoo_pagination_rejects_missing_or_repeated_pages(monkeypatch):
    import yfinance as yf

    fetch = Mock(
        side_effect=[
            {"total": 2, "start": 0, "quotes": [{"symbol": "A"}]},
            {"total": 2, "start": 250, "quotes": [{"symbol": "A"}]},
        ]
    )
    monkeypatch.setattr(yf, "screen", fetch)
    with pytest.raises(ValueError, match="duplicate"):
        YFinanceProvider._screen_rows(object())
    assert fetch.call_count == 2


def test_yahoo_snapshot_keeps_market_cap_time_and_excludes_etfs(monkeypatch):
    provider = YFinanceProvider()
    monkeypatch.setattr(
        provider,
        "_screen_rows",
        lambda q: [
            {
                "symbol": "AAPL",
                "quoteType": "EQUITY",
                "exchange": "NMS",
                "marketCap": 3e12,
                "regularMarketPrice": 200,
                "regularMarketChangePercent": -1.2,
                "regularMarketTime": NOW.timestamp(),
                "longName": "Apple",
            },
            {"symbol": "SPY", "quoteType": "ETF", "exchange": "PCX"},
        ],
    )
    result = provider.fetch_market_snapshot(Market.US, min_market_cap=2e9)
    assert set(result.data) == {"AAPL.US"}
    assert result.data["AAPL.US"].total_mv == 3e12
    assert result.data["AAPL.US"].quote_time == NOW


def test_cached_get_is_authenticated_read_only_and_marks_staleness(monkeypatch):
    cache = Cache()
    monkeypatch.setattr(endpoint, "HeatmapCache", lambda: cache)
    monkeypatch.setattr(endpoint, "utc_now", lambda: NOW)
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/heatmap")
    with TestClient(app) as client:
        assert client.get("/heatmap").status_code == 401
        app.dependency_overrides[require_current_user] = lambda: object()
        assert client.get("/heatmap").json() == {"status": "empty", "snapshot": None}
        cache.value = {
            "market": "US",
            "source": "yfinance",
            "generated_at": (NOW - timedelta(hours=1)).isoformat(),
            "data_as_of": None,
            "data_latest_at": None,
            "classification_observed_at": None,
            "min_market_cap": 2e9,
            "refresh_seconds": 900,
            "excluded_count": 0,
            "unclassified_count": 0,
            "items": [],
        }
        assert client.get("/heatmap", params={"market": "US"}).json()["status"] == "stale"
        assert client.get("/heatmap", params={"market": "HK"}).status_code == 422


def test_weekly_classification_and_directory_refresh_preserve_other_metadata():
    engine = create_engine("sqlite://")
    Instrument.__table__.create(engine)

    class DB:
        @contextmanager
        def session_scope(self):
            with Session(engine) as session, session.begin():
                yield session

        get_session = session_scope

    repository = InstrumentRepository(DB())
    repository.upsert_symbols([{"code": "AAPL.US", "market": "US", "name": "Apple", "metadata": {"ext": 1}}])
    assert (
        repository.save_us_classifications(
            {"AAPL.US": {"sector": "Technology", "industry": "Electronics", "source": "yfinance"}}, NOW
        )
        == 1
    )
    repository.upsert_symbols([{"code": "AAPL.US", "market": "US", "name": "Apple", "metadata": {"ext": 2}}])
    row = repository.get_by_code("AAPL.US")
    assert row.instrument_metadata["ext"] == 2
    assert row.instrument_metadata["classification"]["sector"] == "Technology"
    with pytest.raises(ValueError):
        repository.save_us_classifications({"UNKNOWN.US": {"sector": "Tech"}}, NOW)
    assert repository.get_by_code("AAPL.US").instrument_metadata == row.instrument_metadata
