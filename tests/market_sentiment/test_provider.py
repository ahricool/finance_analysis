"""Offline envelope/pagination tests; not evidence of live account permissions."""

from datetime import date, datetime, timezone
import httpx
import pytest
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoProvider, FuyaoError, date_ms

DAY = date(2026, 9, 15)
STAMP = int(datetime(2026, 9, 15, 11, tzinfo=timezone.utc).timestamp() * 1000)


def payload(page=1, total=201):
    start = (page - 1) * 200
    return {
        "timestamp": STAMP,
        "pagination": {"page": page, "size": 200, "total": total, "pages": (total + 199) // 200},
        "item": [{"thscode": f"{i:06d}.SZ"} for i in range(start, min(start + 200, total))],
    }


def provider(handler):
    return FuyaoProvider(api_key="offline", transport=httpx.MockTransport(handler))


def test_complete_pagination_and_correct_parameters():
    requests = []

    def respond(request):
        params = dict(request.url.params)
        requests.append(params)
        assert params["date_ms"] == str(date_ms(DAY))
        assert params["sort_field"] == "continue_day_cnt"
        assert params["sort_dir"] == "desc"
        assert "offset" not in params and "limit" not in params
        return httpx.Response(200, json={"code": 0, "data": payload(int(params["page"]))})

    result = provider(respond).get_limit_up_pool(DAY)
    assert result.total == len(result.items) == 201
    assert len(requests) == 2 and result.requested_trade_date == DAY


@pytest.mark.parametrize(
    "failure",
    ["missing", "repeat_page", "repeat_code", "changed_total", "changed_time", "wrong_date", "http", "business"],
)
def test_incomplete_is_never_published(failure):
    def respond(request):
        page = int(request.url.params["page"])
        data = payload(page)
        if page == 2:
            if failure == "missing":
                data["item"] = []
            if failure == "repeat_page":
                data = payload(1)
            if failure == "repeat_code":
                data["item"][0]["thscode"] = "000000.SZ"
            if failure == "changed_total":
                data["pagination"]["total"] = 202
            if failure == "changed_time":
                data["timestamp"] += 1000
            if failure == "wrong_date":
                data["date_ms"] = 0
            if failure == "http":
                return httpx.Response(503)
            if failure == "business":
                return httpx.Response(200, json={"code": 3002, "data": None})
        return httpx.Response(200, json={"code": 0, "data": data})

    with pytest.raises(FuyaoError):
        provider(respond).get_limit_up_pool(DAY)


def test_empty_is_valid_but_error_is_not_empty():
    result = provider(lambda r: httpx.Response(200, json={"code": 0, "data": payload(total=0)})).get_limit_up_pool(DAY)
    assert result.total == 0 and result.items == []
    with pytest.raises(FuyaoError, match="3002"):
        provider(lambda r: httpx.Response(200, json={"code": 3002, "data": None})).get_limit_up_pool(DAY)


@pytest.mark.parametrize("kind,sort", [("down", "last_limit_time"), ("break", "open_times")])
def test_optional_sort_contracts(kind, sort):
    def respond(request):
        assert request.url.params["sort_field"] == sort
        return httpx.Response(200, json={"code": 0, "data": payload(total=0)})

    assert getattr(provider(respond), f"get_limit_{kind}_pool")(DAY).total == 0


def test_ladder_window_caps_and_no_posterior():
    keys = ["two_board", "three_board", "four_board", "five_board", "six_board", "seven_over"]
    data = {
        "timestamp": STAMP,
        "window": {"length": 1, "date_list": ["20260915"], "board_caps": dict.fromkeys(keys, 4)},
        "item": [{"date": "20260915", "boards": {k: [{"thscode": "000001.SZ", "seal_nextday": True}] for k in keys}}],
    }
    p = provider(lambda r: httpx.Response(200, json={"code": 0, "data": data}))
    result = p.get_limit_up_ladder()
    assert result.requested_trade_date is None
    assert "seal_nextday" not in str(result.items)
    data["item"][0]["boards"]["two_board"] *= 5
    with pytest.raises(FuyaoError):
        p.get_limit_up_ladder()


def test_bad_pagination_and_readiness_are_sanitized():
    for change in ({"pagination": None}, {"timestamp": 0}, {"date_ms": 0}):
        data = {**payload(total=0), **change}
        p = provider(lambda r: httpx.Response(200, json={"code": 0, "data": data}))
        with pytest.raises(FuyaoError):
            p.get_limit_up_pool(DAY)


def test_capabilities_route_cn_only_with_no_inventory_change():
    from finance_analysis.integrations.market_data.registry import ProviderRegistry, LIMIT_UP_POOL
    from finance_analysis.integrations.market_data.service import MarketDataService

    p = provider(lambda r: httpx.Response(200, json={"code": 0, "data": payload(total=0)}))
    registry = ProviderRegistry()
    registry.register("fuyao", p, capabilities={LIMIT_UP_POOL})
    service = MarketDataService(registry=registry)
    assert service.get_limit_up_pool(DAY).total == 0
    with pytest.raises(ValueError):
        service.get_limit_up_pool(DAY, market="US")
