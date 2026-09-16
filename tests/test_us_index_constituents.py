"""Wikipedia is a reference-data source, separate from market-data fallback."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from finance_analysis.integrations.market_data.providers.us_index_constituents import USIndexConstituentProvider
from finance_analysis.integrations.market_data.service import build_default_registry
from finance_analysis.tasks.celery.jobs.reference_data_sync.service import ReferenceDataSyncService


@pytest.mark.parametrize("index,symbol_column,name_column", [
    ("SP500", "Symbol", "Security"),
    ("NASDAQ100", "Ticker", "Company"),
])
def test_wikipedia_current_constituents_preserve_existing_normalization(index, symbol_column, name_column):
    response = SimpleNamespace(
        text=f"<table><tr><th>{symbol_column}</th><th>{name_column}</th></tr>"
             "<tr><td>AAPL</td><td>Apple</td></tr>"
             "<tr><td>BRK/B</td><td>Berkshire Hathaway</td></tr></table>",
        raise_for_status=Mock(),
    )
    session = Mock()
    session.get.return_value = response
    source = USIndexConstituentProvider(session=session)
    members = source.fetch_index_members(index)
    session.get.assert_called_once_with(source.URLS[index], timeout=30.0,
                                       headers={"User-Agent": "finance-analysis reference-data-sync"})
    response.raise_for_status.assert_called_once()
    assert [member["code"] for member in members] == ["AAPL.US", "BRK.B.US"]
    assert all(member["source"] == "WIKIPEDIA" and member["market"] == "US" for member in members)
    assert members[0]["metadata"]["index_source"] == source.URLS[index]


def test_default_reference_routes_do_not_register_wikipedia_as_market_data(monkeypatch):
    fetch = Mock(return_value=[{"code": "600519.SH"}])
    from finance_analysis.integrations.market_data.providers.akshare_index_constituents import AkShareIndexConstituentProvider
    monkeypatch.setattr(AkShareIndexConstituentProvider, "fetch_index_members", fetch)
    service = ReferenceDataSyncService(
        instrument_repository=object(), universe_repository=object(),
        instrument_primary=object(), instrument_fallback=object(),
    )
    assert set(service.index_providers) == {"AKSHARE", "WIKIPEDIA"}
    assert isinstance(service.index_providers["WIKIPEDIA"], USIndexConstituentProvider)
    assert service.index_providers["AKSHARE"].fetch_index_members("000300") == [{"code": "600519.SH"}]
    fetch.assert_called_once_with("000300")
    registry = build_default_registry()
    assert set(registry.names()) == {"tickflow", "yfinance", "longbridge", "fuyao", "easyquotation"}
    assert "wikipedia" not in registry.names(include_internal=True)
