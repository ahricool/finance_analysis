from __future__ import annotations

from finance_analysis.database.base import Base
from finance_analysis.database.models import Instrument
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.interfaces.api.v1.endpoints.quant import router as quant_router


def test_persisted_schema_excludes_legacy_minute_objects() -> None:
    table_name = "stock" + "_minute"
    confirmation_table = "intraday" + "_confirmation"
    obsolete_flag = "sync" + "_minute"

    assert table_name not in Base.metadata.tables
    assert confirmation_table not in Base.metadata.tables
    assert obsolete_flag not in Instrument.__table__.columns


def test_quant_router_excludes_legacy_confirmation_endpoints() -> None:
    removed_path_fragment = "intraday" + "-confirmations"
    assert all(removed_path_fragment not in route.path for route in quant_router.routes)


def test_realtime_minute_market_data_service_remains_available() -> None:
    assert callable(MarketDataService.get_minute_bars)
