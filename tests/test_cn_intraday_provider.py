from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import requests

from finance_analysis.integrations.market_data.models import MinuteBarsRequest
from finance_analysis.integrations.market_data.providers.cn_intraday import CN_TZ, CnIntradayProvider, _Pacer
from finance_analysis.integrations.market_data.registry import MINUTE_BARS, ProviderRegistry
from finance_analysis.integrations.market_data.service import MarketDataService

START = datetime(2026, 10, 23, 1, 30, tzinfo=timezone.utc)
END = START + timedelta(minutes=3, seconds=10)


def sina_row(at="09:31", **kwargs):
    return {
        "day": f"2026-10-23 {at}:00",
        "open": "10",
        "high": "12",
        "low": "9",
        "close": "11",
        "volume": "123",
        "amount": "1300",
        **kwargs,
    }


def request(symbol="600000.SH", **kwargs):
    return MinuteBarsRequest((symbol,), START, END, **kwargs)


def test_sina_end_labels_become_utc_starts_auction_excluded_and_active_not_confirmed():
    rows = [sina_row("09:30"), sina_row(), sina_row("09:32"), sina_row("09:34")]
    provider = CnIntradayProvider("sina_intraday", lambda symbol: rows)
    closed = provider.fetch_minute_bars(request()).data["600000.SH"]
    assert [bar.bar_time for bar in closed] == [START, START + timedelta(minutes=1)]
    assert closed[0].bar_start == START and closed[0].bar_end == START + timedelta(minutes=1)
    assert closed[0].volume == 123 and closed[0].amount == 1300
    all_bars = provider.fetch_minute_bars(request(include_incomplete=True)).data["600000.SH"]
    assert len(all_bars) == 3 and all_bars[-1].bar_end > END


@pytest.mark.parametrize(
    "symbol,multiplier",
    [("600000.SH", 100), ("300308.SZ", 100), ("688521.SH", 1), ("689009.SH", 1), ("510300.SH", 100)],
)
def test_tencent_units_and_missing_amount_are_not_invented(symbol, multiplier):
    provider = CnIntradayProvider(
        "tencent_intraday",
        lambda symbol: [
            ["202610230931", "10", "11", "12", "9", "123.12", {}, "1.02"],
        ],
    )
    bar = provider.fetch_minute_bars(request(symbol)).data[symbol][0]
    assert (bar.open, bar.high, bar.low, bar.close) == (10, 12, 9, 11)
    assert bar.volume == round(123.12 * multiplier)
    assert bar.amount is None and not bar.amount_estimated


@pytest.mark.parametrize(
    "bad", [{"open": "0"}, {"high": "8"}, {"volume": "-1"}, {"close": "nan"}, {"amount": "inf"}, {"amount": "-1"}]
)
def test_invalid_ohlcv_is_explicit_failure(bad):
    result = CnIntradayProvider("sina_intraday", lambda symbol: [sina_row(**bad)]).fetch_minute_bars(request())
    assert not result.data and "600000.SH" in result.failed_symbols


def test_session_boundaries_and_sparse_bj_minutes_are_preserved_without_fill():
    rows = [sina_row(at) for at in ["09:30", "09:31", "09:35", "11:30", "11:31", "13:00", "13:01", "15:00", "15:01"]]
    provider = CnIntradayProvider("sina_intraday", lambda symbol: rows)
    result = provider.fetch_minute_bars(replace(request("920002.BJ"), end_time=START + timedelta(hours=6)))
    bars = result.data["920002.BJ"]
    assert [bar.bar_start.astimezone(CN_TZ).strftime("%H:%M") for bar in bars] == [
        "09:30",
        "09:34",
        "11:29",
        "13:00",
        "14:59",
    ]
    fallback = CnIntradayProvider("tencent_intraday", lambda symbol: pytest.fail("BJ must not issue HTTP"))
    assert "920002.BJ" in fallback.fetch_minute_bars(request("920002.BJ")).failed_symbols


@pytest.mark.parametrize("failure", ["timeout", "empty", "stale", "invalid"])
def test_single_fallback_replaces_symbol_window_after_transport_empty_stale_or_invalid_primary(failure):
    calls = []

    def primary(symbol):
        if symbol == "000001.SZ":
            return [sina_row("09:33")]
        if failure == "timeout":
            raise requests.Timeout("timeout")
        return {"empty": [], "stale": [sina_row()], "invalid": [sina_row("09:33", high="1")]}[failure]

    def secondary(symbol):
        calls.append(symbol)
        return [["202610230933", "10", "11", "12", "9", "123", {}]]

    registry = ProviderRegistry()
    registry.register("sina_intraday", CnIntradayProvider("sina_intraday", primary), capabilities={MINUTE_BARS})
    registry.register("tencent_intraday", CnIntradayProvider("tencent_intraday", secondary), capabilities={MINUTE_BARS})
    result = MarketDataService(registry).get_minute_bars(
        ["600000.SH", "000001.SZ"],
        START,
        END,
        providers=("sina_intraday", "tencent_intraday"),
        minimum_latest_bar_time=START + timedelta(minutes=2),
    )
    assert calls == ["600000.SH"]
    assert result.providers_used == {"000001.SZ": "sina_intraday", "600000.SH": "tencent_intraday"}
    assert not result.failed_symbols and not result.request_errors
    assert result.fallback_symbols == ["600000.SH"] and result.fallback_reasons["600000.SH"]


def test_process_pacer_does_not_burst_and_respects_request_budget(monkeypatch):
    from finance_analysis.integrations.market_data.providers import cn_intraday
    from finance_analysis.integrations.market_data.request_budget import BudgetExhausted

    clock = [0.0]
    monkeypatch.setattr(cn_intraday, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cn_intraday, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    pacer = _Pacer()
    for _ in range(3):
        pacer.wait()
    assert clock[0] == 2
    monkeypatch.setattr(cn_intraday, "remaining_seconds", lambda: 0.5)
    with pytest.raises(BudgetExhausted):
        pacer.wait()


def test_slow_primary_is_given_only_part_of_the_shared_budget():
    from finance_analysis.integrations.market_data.request_budget import remaining_seconds

    budgets = {}

    def primary(symbol):
        budgets["primary"] = remaining_seconds()
        raise requests.Timeout("timeout")

    def secondary(symbol):
        budgets["fallback"] = remaining_seconds()
        return [["202610230933", "10", "11", "12", "9", "123", {}]]

    registry = ProviderRegistry()
    registry.register("sina_intraday", CnIntradayProvider("sina_intraday", primary), capabilities={MINUTE_BARS})
    registry.register("tencent_intraday", CnIntradayProvider("tencent_intraday", secondary), capabilities={MINUTE_BARS})
    result = MarketDataService(registry).get_minute_bars(
        ["600000.SH"], START, END, providers=("sina_intraday", "tencent_intraday"),
        minimum_latest_bar_time=START + timedelta(minutes=2),
    )
    assert not result.failed_symbols
    assert 0 < budgets["primary"] <= 9
    assert budgets["fallback"] > budgets["primary"]


def test_required_session_window_falls_back_without_mixing_source_bars():
    registry = ProviderRegistry()
    registry.register('sina_intraday', CnIntradayProvider('sina_intraday', lambda symbol: [sina_row('09:33')]), capabilities={MINUTE_BARS})
    registry.register('tencent_intraday', CnIntradayProvider('tencent_intraday', lambda symbol: [
        [f'2026102309{31+i:02d}', '10', '11', '12', '9', '123', {}] for i in range(3)
    ]), capabilities={MINUTE_BARS})
    result = MarketDataService(registry).get_minute_bars(
        ['512800.SH'], START, END, providers=('sina_intraday', 'tencent_intraday'),
        required_bar_starts=tuple(START+timedelta(minutes=i) for i in range(3)),
    )
    assert result.providers_used == {'512800.SH': 'tencent_intraday'}
    assert len(result.data['512800.SH']) == 3
    assert {b.provider for b in result.data['512800.SH']} == {'tencent_intraday'}
    assert 'gaps' in result.fallback_reasons['512800.SH'][0]


def test_incomplete_only_source_is_unavailable_when_full_window_required():
    registry = ProviderRegistry()
    registry.register('sina_intraday', CnIntradayProvider('sina_intraday', lambda symbol: [sina_row('09:33')]), capabilities={MINUTE_BARS})
    result = MarketDataService(registry).get_minute_bars(
        ['512800.SH'], START, END, providers=('sina_intraday',), required_bar_starts=(START,),
    )
    assert not result.data
    assert '512800.SH' in result.failed_symbols
