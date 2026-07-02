# -*- coding: utf-8 -*-
"""Tests for A-share board classification and price-limit resolution."""

from __future__ import annotations

from datetime import date

from finance_analysis.tasks.celery.jobs.a_share_intraday_analysis.price_limits import (
    BOARD_BSE,
    BOARD_CHINEXT,
    BOARD_CONVERTIBLE_BOND,
    BOARD_ETF,
    BOARD_MAIN,
    BOARD_NEW_LISTING,
    BOARD_ST,
    BOARD_STAR,
    classify_a_share_board,
    resolve_price_limit_rule,
)


def test_main_board_normal_stock_uses_10_percent():
    rule = resolve_price_limit_rule(code="600519", name="贵州茅台", pre_close=100.0)
    assert rule.board == BOARD_MAIN
    assert rule.limit_ratio == 0.10
    assert rule.limit_up_price == 110.0
    assert rule.limit_down_price == 90.0
    assert rule.has_price_limit is True


def test_chinext_stock_uses_20_percent():
    rule = resolve_price_limit_rule(code="300750", name="宁德时代", pre_close=100.0)
    assert rule.board == BOARD_CHINEXT
    assert rule.limit_ratio == 0.20
    assert rule.limit_up_price == 120.0


def test_star_market_stock_uses_20_percent():
    rule = resolve_price_limit_rule(code="688981", name="中芯国际", pre_close=100.0)
    assert rule.board == BOARD_STAR
    assert rule.limit_ratio == 0.20
    assert rule.limit_up_price == 120.0


def test_bse_stock_uses_30_percent():
    rule = resolve_price_limit_rule(code="920748", name="某北交所", pre_close=100.0)
    assert rule.board == BOARD_BSE
    assert rule.limit_ratio == 0.30
    assert rule.limit_up_price == 130.0


def test_risk_warning_main_board_uses_5_percent():
    rule = resolve_price_limit_rule(code="600100", name="ST康美", pre_close=100.0)
    assert rule.board == BOARD_ST
    assert rule.limit_ratio == 0.05
    assert rule.limit_up_price == 105.0


def test_risk_warning_chinext_keeps_20_percent():
    # ChiNext ST stocks keep ±20%, not the 5% main-board rule.
    rule = resolve_price_limit_rule(code="300999", name="ST创业", pre_close=100.0)
    assert rule.board == BOARD_ST
    assert rule.limit_ratio == 0.20
    assert rule.limit_up_price == 120.0


def test_etf_has_no_stock_price_limit():
    rule = resolve_price_limit_rule(code="510300", name="沪深300ETF", pre_close=4.0)
    assert rule.board == BOARD_ETF
    assert rule.has_price_limit is False
    assert rule.limit_up_price is None


def test_convertible_bond_has_no_stock_price_limit():
    rule = resolve_price_limit_rule(code="113050", name="南银转债", pre_close=120.0)
    assert rule.board == BOARD_CONVERTIBLE_BOND
    assert rule.has_price_limit is False


def test_new_listing_unbounded_not_treated_as_limit():
    today = date(2026, 6, 24)
    rule = resolve_price_limit_rule(
        code="688001",
        name="新科创",
        pre_close=50.0,
        listing_date=today,
        today=today,
    )
    assert rule.board == BOARD_NEW_LISTING
    assert rule.has_price_limit is False
    assert rule.limit_up_price is None


def test_exchange_provided_limits_take_priority():
    rule = resolve_price_limit_rule(
        code="600519",
        name="贵州茅台",
        pre_close=100.0,
        explicit_limit_up=109.5,
        explicit_limit_down=90.5,
    )
    assert rule.source == "exchange"
    assert rule.limit_up_price == 109.5
    assert rule.limit_down_price == 90.5


def test_float_precision_does_not_create_false_limit():
    # 2.95 * 1.1 = 3.2450000000000006 in float; Decimal keeps it clean.
    rule = resolve_price_limit_rule(code="600000", name="浦发银行", pre_close=2.95)
    assert rule.limit_up_price == 3.25
    assert rule.limit_down_price == 2.66


def test_missing_pre_close_returns_unknown_not_10_percent():
    rule = resolve_price_limit_rule(code="600519", name="贵州茅台", pre_close=None)
    assert rule.limit_up_price is None
    assert rule.source == "unknown"


def test_classify_board_labels():
    assert classify_a_share_board("600519", "贵州茅台") == BOARD_MAIN
    assert classify_a_share_board("000001", "平安银行") == BOARD_MAIN
    assert classify_a_share_board("300750", "宁德时代") == BOARD_CHINEXT
    assert classify_a_share_board("688981", "中芯国际") == BOARD_STAR
    assert classify_a_share_board("920748", "某北交所") == BOARD_BSE
    assert classify_a_share_board("510300", "ETF") == BOARD_ETF
