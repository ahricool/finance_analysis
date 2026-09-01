import pytest
from fastapi import HTTPException

from finance_analysis.integrations.market_data.models import (
    BatchInstrumentResult,
    InstrumentInfo,
    Market,
)
from finance_analysis.interfaces.api.v1.endpoints import stocks


def test_stock_info_uses_canonical_code_and_provider_fallback(monkeypatch):
    calls = []

    class FakeMarketDataService:
        def get_instrument_info(self, codes):
            calls.append(list(codes))
            return BatchInstrumentResult(
                data={
                    "600519.SH": InstrumentInfo(
                        symbol="600519.SH",
                        market=Market.CN,
                        name="贵州茅台",
                        provider="tickflow",
                        currency="CNY",
                        exchange="SH",
                        instrument_type="stock",
                    )
                },
                providers_used={"600519.SH": "tickflow"},
            )

    monkeypatch.setattr(stocks, "MarketDataService", FakeMarketDataService)

    response = stocks.get_stock_info("600519")

    assert calls == [["600519.SH"]]
    assert response.code == "600519.SH"
    assert response.name == "贵州茅台"
    assert response.provider == "tickflow"
    assert "lot_size" not in response.model_dump()


def test_stock_info_returns_not_found_when_all_providers_miss(monkeypatch):
    class FakeMarketDataService:
        def get_instrument_info(self, codes):
            return BatchInstrumentResult(
                missing_symbols=list(codes),
                failed_symbols={codes[0]: "all providers missed"},
            )

    monkeypatch.setattr(stocks, "MarketDataService", FakeMarketDataService)

    with pytest.raises(HTTPException) as error:
        stocks.get_stock_info("AAPL")

    assert error.value.status_code == 404
    assert error.value.detail == "all providers missed"
