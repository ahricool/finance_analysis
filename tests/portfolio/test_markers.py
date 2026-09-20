"""Daily BST markers from trade operations."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from finance_analysis.portfolio.markers import markers_from_operations  # pragma: allowlist secret

SH = ZoneInfo("Asia/Shanghai")


def test_same_day_buy_sell_is_t():
    ops = [
        SimpleNamespace(side="BUY", executed_at=datetime(2026, 9, 1, 9, 45, tzinfo=SH), quantity=Decimal("500"), price=Decimal("10.20"), note=None),
        SimpleNamespace(side="SELL", executed_at=datetime(2026, 9, 1, 14, 20, tzinfo=SH), quantity=Decimal("300"), price=Decimal("10.65"), note=None),
    ]
    markers = markers_from_operations(ops, market="CN")
    assert [item.type for item in markers] == ["T"]
    assert len(markers[0].operations) == 2


def test_buy_only_is_b_and_sell_only_is_s():
    buy = [SimpleNamespace(side="BUY", executed_at=datetime(2026, 9, 1, 9, 45, tzinfo=SH), quantity=Decimal("1"), price=Decimal("1"), note=None)]
    sell = [SimpleNamespace(side="SELL", executed_at=datetime(2026, 9, 2, 9, 45, tzinfo=SH), quantity=Decimal("1"), price=Decimal("1"), note=None)]
    assert markers_from_operations(buy, market="CN")[0].type == "B"
    assert markers_from_operations(sell, market="CN")[0].type == "S"
