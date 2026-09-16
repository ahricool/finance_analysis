"""CSI membership uses AkShare independently from the market-data inventory."""
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from finance_analysis.integrations.market_data.providers.akshare_index_constituents import (
    AkShareIndexConstituentProvider,
)
from finance_analysis.tasks.celery.jobs.reference_data_sync.service import ReferenceDataSyncService


@pytest.mark.parametrize("index", ["000300", "000905", "000852", "932000"])
def test_original_csindex_api_and_canonical_members(monkeypatch, index):
    fetch = Mock(return_value=pd.DataFrame([
        {"成分券代码": "600519", "成分券名称": "贵州茅台"},
        {"成分券代码": "000001", "成分券名称": "平安银行"},
    ]))
    monkeypatch.setattr("akshare.index_stock_cons_csindex", fetch)
    result = AkShareIndexConstituentProvider().fetch_index_members(index)
    fetch.assert_called_once_with(symbol=index)
    assert [row["code"] for row in result] == ["600519.SH", "000001.SZ"]
    assert all(row["source"] == "AKSHARE" for row in result)


@pytest.mark.parametrize("failure", ["request", "empty"])
def test_cn_failure_does_not_replace_existing_members(monkeypatch, failure):
    fetch = Mock(side_effect=RuntimeError("upstream failed")) if failure == "request" else Mock(return_value=pd.DataFrame())
    monkeypatch.setattr("akshare.index_stock_cons_csindex", fetch)
    universe = Mock()
    service = ReferenceDataSyncService(
        instrument_repository=object(), universe_repository=universe,
        instrument_primary=object(), instrument_fallback=object(),
        index_providers={"AKSHARE": AkShareIndexConstituentProvider(), "WIKIPEDIA": Mock()},
    )
    service.index_providers["WIKIPEDIA"].fetch_index_members.return_value = []
    service.instrument_sync.sync_instruments_detailed = lambda market: SimpleNamespace(
        fetched=0, inserted=0, updated=0, fallback_used=False, provider="TICKFLOW",
    )
    result = service.run()
    assert result["universe_count"] == 0
    assert all(key in result["failed_universes"] for key in ("cn_csi300", "cn_csi500", "cn_csi1000", "cn_csi2000"))
    universe.replace_members_with_stats.assert_not_called()
