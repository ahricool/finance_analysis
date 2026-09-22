from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoProvider, FuyaoError
from finance_analysis.integrations.market_data.registry import (
    ProviderRegistry,
    INDUSTRY_CATALOG,
    INDEX_HISTORY,
    INDEX_CONSTITUENTS,
)
from finance_analysis.integrations.market_data.service import MarketDataService


def provider(monkeypatch, handler):
    return FuyaoProvider(api_key="offline-test-key", transport=httpx.MockTransport(handler))


def test_reusable_cn_provider_protocol_and_no_secret_in_params(monkeypatch):
    day = date(2026, 9, 16)
    timestamp = int(datetime(2026, 9, 16, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000)

    def handle(request):
        assert request.headers["X-api-key"] == "offline-test-key"
        assert "offline-test-key" not in str(request.url)
        if request.url.path.endswith("historical"):
            assert request.url.params["interval"] == "1d"
            assert int(request.url.params["start"]) == timestamp
            assert int(request.url.params["end"]) == timestamp + 86400000 - 1
            item = [
                dict(
                    date_ms=timestamp,
                    open_price=10,
                    high_price=11,
                    low_price=9,
                    close_price=10,
                    turnover=1000,
                    volume=100,
                )
            ]
        elif request.url.path.endswith("ths-index-list"):
            assert request.url.params["tag"] == "industry"
            item = [dict(thscode="881101.TI", name="行业")]
        else:
            item = [dict(thscode="600001.SH", name="成分")]
        return httpx.Response(200, json={"code": 0, "data": {"timestamp": timestamp, "item": item}})

    p = provider(monkeypatch, handle)
    registry = ProviderRegistry()
    registry.register("fuyao", p, capabilities={INDUSTRY_CATALOG, INDEX_HISTORY, INDEX_CONSTITUENTS})
    service = MarketDataService(registry=registry)
    assert service.get_industry_catalog()[0]["thscode"] == "881101.TI"
    bars, ts = service.get_index_history("000300.SH", day, day)
    assert bars[0].trade_date == day and bars[0].amount == 1000 and ts.tzinfo is not None
    assert service.get_index_constituents("881101.TI")[0]["thscode"] == "600001.SH"
    for market in ["US", "HK"]:
        with pytest.raises(ValueError, match="A shares"):
            service.get_industry_catalog(market)
    with pytest.raises(ValueError, match="A-share"):
        p.get_index_constituents("AAPL.US")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429),
        httpx.Response(503),
        httpx.Response(200, json={"code": 4001}),
        httpx.Response(200, json={"code": 2001, "message": "secret-body"}),
        httpx.Response(200, json={"code": 0, "data": {"item": []}}),
    ],
)
def test_errors_are_bounded_and_sanitized(monkeypatch, response):
    monkeypatch.setattr("finance_analysis.integrations.market_data.providers.fuyao.sleep", lambda _: None)
    calls = []
    p = provider(monkeypatch, lambda r: calls.append(r) or response)
    with pytest.raises(FuyaoError) as error:
        p.get_industry_catalog()
    limited = response.status_code == 429 or (response.status_code == 200 and response.json().get("code") == 4001)
    assert len(calls) == (4 if limited else 1)
    assert "secret-body" not in str(error.value) and "offline-test-key" not in str(error.value)


def test_unified_provider_identity_and_existing_routes_unchanged():
    from finance_analysis.integrations.market_data.config import DEFAULT_PROVIDER_ORDER
    from finance_analysis.integrations.market_data.service import build_default_registry
    registry = build_default_registry()
    assert set(registry.names()) == {
        "alpaca", "tickflow", "yfinance", "longbridge", "fuyao", "easyquotation", "sina_minute",
    }
    assert type(registry.get("fuyao").provider) is FuyaoProvider
    from finance_analysis.integrations.market_data.models import Market
    for capability in (INDUSTRY_CATALOG, INDEX_HISTORY, INDEX_CONSTITUENTS):
        assert capability in registry.capabilities("fuyao")
        assert DEFAULT_PROVIDER_ORDER[Market.CN, capability] == ("fuyao",)
