"""Offline official-contract fixtures; no real API or LLM calls."""

import httpx
import pytest

from finance_analysis.integrations.polymarket.client import Client, PolymarketError
from finance_analysis.prediction_markets.live import live_projection, changes


def client(handler):
    return Client(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None)


def event(**extra):
    return dict(
        id="99999999999999999999",
        title="Nvidia export restrictions",
        description="Technology exports",
        tags=[{"id": "1", "slug": "tech"}],
        **extra,
    )


def test_history_cursor_empty_page_seconds_and_long_range():
    requests = []

    def handler(req):
        requests.append(req)
        assert req.url.path == "/v2/prices-history"
        assert req.url.params["token_id"] == "9999999999999999999999"
        if "cursor" not in req.url.params:
            return httpx.Response(200, json={"data": [], "pagination": {"next_cursor": "two", "has_more": True}})
        return httpx.Response(
            200,
            json={
                "data": [{"timestamp": 123456, "price": 0, "resolution_seconds": 300}],
                "pagination": {"next_cursor": None},
            },
        )

    c = client(handler)
    assert c.history("9999999999999999999999", start=1, end=31 * 86400) == [
        dict(timestamp=123456, price=0, resolution_seconds=300)
    ]
    assert len(requests) == 6
    assert all(int(r.url.params["end"]) - int(r.url.params["start"]) <= 15 * 86400 for r in requests)
    c.history("9999999999999999999999", as_of=123456)
    assert requests[-1].url.params["as_of"] == "123456"
    assert "interval" not in requests[-1].url.params


def test_interrupted_or_repeated_pages_fail_not_complete():
    c = client(lambda req: httpx.Response(200, json={"data": [], "pagination": {"next_cursor": "same"}}))
    with pytest.raises(PolymarketError, match="repeated_history_cursor"):
        c.history("1", interval="max")
    c = client(lambda req: httpx.Response(429, headers={"Retry-After": "31"}))
    with pytest.raises(PolymarketError):
        c.search("NVIDIA")


def test_live_hierarchy_v2_positions_big_ids_no_yes_assumption_or_zero_loss():
    raw = event(
        markets=[
            dict(
                id="10",
                version="v1",
                question="One?",
                volume=100,
                outcomes='["No", "Yes"]',
                outcomePrices='["0", "1"]',
                clobTokenIds='["99999999999999999999", "2"]',
            ),
            dict(
                id="11",
                version="v2",
                question="Two?",
                volume=0,
                outcomes=["Up", "Down"],
                outcomePrices=["0.5", "0.5"],
                positionIds=["3", "4"],
            ),
            dict(
                id="12",
                version="v2",
                resolutionStatus="resolved",
                outcomes=["No", "Yes"],
                outcomePrices=["1", "0"],
                positionIds=["5", "6"],
            ),
        ]
    )
    result = live_projection(raw)
    assert [m["id"] for m in result["markets"]] == ["10", "11", "12"]
    assert result["markets"][0]["outcomes"][0] == dict(
        id="99999999999999999999", label="No", probability=0, price_type="gamma_outcome_price", missing_reason=None
    )
    assert result["markets"][1]["outcomes"][0]["id"] == "3"
    assert result["markets"][1]["outcomes"][0]["probability"] is None
    assert result["markets"][2]["outcomes"][1]["price_type"] == "settlement"


def test_history_changes_same_series_tolerances_and_closed():
    now = 2_000_000
    points = [
        dict(timestamp=now - 7 * 86400, price=0.2, resolution_seconds=300),
        dict(timestamp=now - 86400, price=0.4, resolution_seconds=300),
        dict(timestamp=now, price=0.5, resolution_seconds=0),
    ]
    result = changes(points, now)
    assert result["24h"]["percentage_points"] == 10
    assert result["7d"]["percentage_points"] == 30
    assert changes(points, now + 901)["24h"]["percentage_points"] is None
    assert changes(points, now, closed=True)["24h"]["percentage_points"] is None
    points[1]["resolution_seconds"] = 43200
    assert changes(points, now)["24h"]["percentage_points"] is None
