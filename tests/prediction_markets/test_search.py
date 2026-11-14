import httpx
from finance_analysis.integrations.polymarket.client import Client, PolymarketError
from finance_analysis.prediction_markets.live import LiveService
from finance_analysis.prediction_markets.search import search_stock, search_terms


class Redis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex):
        self.data[key] = value


def row(i, **kwargs):
    return dict(id=str(i), title=f"Event {i}", slug=f"event-{i}", **kwargs)


def test_search_contract_and_no_catalog_requests():
    requests = []

    def handler(req):
        requests.append(req)
        return httpx.Response(200, json={"events": [row(1)], "pagination": {"hasMore": True}})

    c = Client(httpx.Client(transport=httpx.MockTransport(handler)))
    assert c.search("NVIDIA") == [row(1)]
    assert len(requests) == 1
    assert requests[0].url.path == "/public-search"
    assert dict(requests[0].url.params)["events_status"] == "active"
    assert requests[0].url.params["limit_per_type"] == "20"


def test_official_order_dedup_twenty_limit_and_cache():
    calls = []

    class Client:
        def search(self, term):
            calls.append(term)
            return [row(i, volume24hr=100 - i) for i in (range(15) if term == "NVIDIA" else range(10, 30))]

    service = LiveService(client=Client(), redis=Redis())
    first = search_stock("NVDA.US", "NVIDIA Corporation", service)
    assert [x["event_id"] for x in first["items"]] == list(map(str, range(20)))
    assert calls == ["NVIDIA", "NVDA"]
    assert search_stock("NVDA.US", "NVIDIA Corporation", service)["cache_status"] == "hit"
    assert len(calls) == 2
    assert first["sort"] == "official_relevance"


def test_empty_failure_partial_closed_and_missing_volume():
    class Client:
        def search(self, term):
            if term == "AI":
                raise PolymarketError("offline")
            return [row(1, closed=True), row(2, volume24hr=0), row(3, volume24hr="NaN")]

    service = LiveService(client=Client(), redis=Redis())
    result = search_stock("AI.US", "C3 AI", service)
    assert result["partial"] and [x["event_id"] for x in result["items"]] == ["2", "3"]
    assert [x["volume_24h"] for x in result["items"]] == [0, None]
    assert search_stock("AI.US", None, service)["status"] == "unavailable"
    service.client.search = lambda term: []
    assert search_stock("EMPTY.US", None, service)["items"] == []
    assert search_terms("0700.HK", "腾讯控股") == ["腾讯控股", "0700"]


def test_cache_key_isolates_canonical_market_and_name_change():
    class Client:
        def search(self, term):
            return []

    service = LiveService(client=Client(), redis=Redis())
    assert search_stock("ABC.US", None, service)["symbol"] == "ABC.US"
    assert search_stock("ABC.HK", None, service)["symbol"] == "ABC.HK"
    assert search_stock("ABC.US", "New company", service)["cache_status"] == "miss"
