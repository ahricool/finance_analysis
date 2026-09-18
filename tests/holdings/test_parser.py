"""Offline parser tests for Google Sheet holdings. Synthetic rows only."""

from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from finance_analysis.holdings.parser import SheetParseError, group_positions, parse_accounts, parse_decimal, parse_legs  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.spreadsheet import SpreadsheetIdError, parse_spreadsheet_id  # pragma: allowlist secret

SH = ZoneInfo("Asia/Shanghai")


def test_parse_spreadsheet_id_from_docs_url_without_fetching():
    assert parse_spreadsheet_id("1AbCdefghijklmnopqrstuvwxy") == "1AbCdefghijklmnopqrstuvwxy"
    assert (
        parse_spreadsheet_id("https://docs.google.com/spreadsheets/d/1AbCdefghijklmnopqrstuvwxy/edit#gid=0")
        == "1AbCdefghijklmnopqrstuvwxy"
    )
    with pytest.raises(SpreadsheetIdError):
        parse_spreadsheet_id("https://evil.example/d/1AbCdefghijklmnopqrstuvwxy")


def test_accounts_and_legs_parse_by_header_and_reject_core_count():
    accounts = parse_accounts(
        [
            ["account_id", "account_name", "base_currency", "net_asset", "nav_as_of", "holdings_as_of", "positions_complete"],
            ["a1", "CN", "CNY", 100000.5, 45921.5, 45921.5, True],
        ],
        tz=SH,
    )
    assert accounts[0].net_asset == Decimal("100000.5")
    assert accounts[0].nav_as_of.tzinfo is not None
    legs = parse_legs(
        [
            ["account_id", "position_id", "leg_id", "leg_role", "symbol", "asset_type", "quantity", "entry_price", "entry_time", "status"],
            ["a1", "p1", "c1", "CORE", "600519.SH", "STOCK", "1000", "1400.1", "2026-01-05T10:00:00", "OPEN"],
            ["a1", "p1", "a1", "ADDON", "600519.SH", "STOCK", "500", "1450", "2026-02-05T10:00:00", "OPEN"],
        ],
        tz=SH,
    )
    positions = group_positions(legs)
    assert len(positions) == 1
    assert [item.leg_role for item in positions[0].legs] == ["CORE", "ADDON"]
    with pytest.raises(SheetParseError, match="CORE"):
        group_positions(
            parse_legs(
                [
                    ["account_id", "position_id", "leg_id", "leg_role", "symbol", "asset_type", "quantity", "entry_price", "entry_time", "status"],
                    ["a1", "p2", "c1", "ADDON", "AAPL.US", "STOCK", "10", "100", "2026-01-05T10:00:00", "OPEN"],
                ],
                tz=SH,
            )
        )


def test_uncovered_hk_is_kept_and_float_money_uses_decimal_string():
    value = parse_decimal(0.1, field="qty")
    assert format(value, "f").startswith("0.1")
    legs = parse_legs(
        [
            ["account_id", "position_id", "leg_id", "leg_role", "symbol", "asset_type", "quantity", "entry_price", "entry_time", "status"],
            ["a1", "p1", "c1", "CORE", "0700.HK", "STOCK", "100", "300", "2026-01-05T10:00:00+08:00", "OPEN"],
        ],
        tz=SH,
    )
    assert legs[0].coverage == "UNCOVERED_MARKET"
    assert legs[0].canonical_symbol == "700.HK"
    assert legs[0].symbol == "0700.HK"
