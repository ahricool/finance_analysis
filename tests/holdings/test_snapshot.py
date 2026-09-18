"""Snapshot hash excludes fetched_at; unexpected empty is rejected. Synthetic sheet rows."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from finance_analysis.holdings.snapshot import SnapshotRejected, build_snapshot, content_hash  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.client import SheetBatch  # pragma: allowlist secret

SH = ZoneInfo("Asia/Shanghai")
HEADERS_A = ["account_id", "account_name", "base_currency", "net_asset", "nav_as_of", "holdings_as_of", "positions_complete"]
HEADERS_P = ["account_id", "position_id", "leg_id", "leg_role", "symbol", "asset_type", "quantity", "entry_price", "entry_time", "status"]


def _batch(accounts, positions, fetched=None):
    return SheetBatch(spreadsheet_id="sheet", timezone="Asia/Shanghai", title="t", values={"Accounts": accounts, "Positions": positions})


def test_content_hash_ignores_fetched_at_and_generation():
    accounts = [HEADERS_A, ["a1", "CN", "CNY", 100000, "2026-09-16T15:00:00+08:00", "2026-09-16T15:00:00+08:00", True]]
    positions = [HEADERS_P, ["a1", "p1", "c1", "CORE", "600519.SH", "STOCK", "100", "10", "2026-01-05T10:00:00+08:00", "OPEN"]]
    first = build_snapshot(uid=1, source_id=1, batch=_batch(accounts, positions), generation=1, now=datetime(2026, 9, 16, 8, tzinfo=timezone.utc))
    second = build_snapshot(uid=1, source_id=1, batch=_batch(accounts, positions), generation=9, now=datetime(2026, 9, 17, 8, tzinfo=timezone.utc))
    assert first.content_hash == second.content_hash
    assert content_hash(first) == first.content_hash


def test_legal_closed_zero_quantity_is_published():
    accounts = [HEADERS_A, ["a1", "CN", "CNY", 100000, "2026-09-16T15:00:00+08:00", "2026-09-16T15:00:00+08:00", True]]
    open_rows = [HEADERS_P, ["a1", "p1", "c1", "CORE", "600519.SH", "STOCK", "100", "10", "2026-01-05T10:00:00+08:00", "OPEN"]]
    previous = build_snapshot(uid=1, source_id=1, batch=_batch(accounts, open_rows), generation=1, now=datetime(2026, 9, 16, 8, tzinfo=timezone.utc))
    closed_rows = [HEADERS_P, ["a1", "p1", "c1", "CORE", "600519.SH", "STOCK", "0", "10", "2026-01-05T10:00:00+08:00", "CLOSED"]]
    snapshot = build_snapshot(
        uid=1,
        source_id=1,
        batch=_batch(accounts, closed_rows),
        generation=2,
        previous=previous,
        now=datetime(2026, 9, 17, 8, tzinfo=timezone.utc),
    )
    assert snapshot.status == "VALID"
    assert snapshot.accounts[0].validity == "EMPTY_VALID"
    assert snapshot.positions[0].legs[0].status == "CLOSED"
    assert snapshot.positions[0].legs[0].quantity == 0


def test_open_supported_asset_requires_positive_quantity_and_price():
    accounts = [HEADERS_A, ["a1", "CN", "CNY", 100000, "2026-09-16T15:00:00+08:00", "2026-09-16T15:00:00+08:00", True]]
    with pytest.raises(SnapshotRejected):
        build_snapshot(
            uid=1,
            source_id=1,
            batch=_batch(accounts, [HEADERS_P, ["a1", "p1", "c1", "CORE", "600519.SH", "STOCK", "0", "10", "2026-01-05T10:00:00+08:00", "OPEN"]]),
            generation=1,
            now=datetime(2026, 9, 16, 8, tzinfo=timezone.utc),
        )


def test_unexpected_empty_after_open_legs_is_rejected():
    accounts = [HEADERS_A, ["a1", "CN", "CNY", 100000, "2026-09-16T15:00:00+08:00", "2026-09-16T15:00:00+08:00", True]]
    positions = [HEADERS_P, ["a1", "p1", "c1", "CORE", "600519.SH", "STOCK", "100", "10", "2026-01-05T10:00:00+08:00", "OPEN"]]
    previous = build_snapshot(uid=1, source_id=1, batch=_batch(accounts, positions), generation=1, now=datetime(2026, 9, 16, 8, tzinfo=timezone.utc))
    with pytest.raises(SnapshotRejected, match="空表"):
        build_snapshot(
            uid=1,
            source_id=1,
            batch=_batch(accounts, [HEADERS_P]),
            generation=2,
            previous=previous,
            now=datetime(2026, 9, 17, 8, tzinfo=timezone.utc),
        )
