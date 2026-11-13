import threading
from concurrent.futures import ThreadPoolExecutor

from finance_analysis.prediction_markets.live import LiveService
from finance_analysis.prediction_markets.config import Config


class Redis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex):
        self.data[key] = value


def test_cache_times_stale_expiry_and_outage():
    now, calls = [1000], []
    service = LiveService(client=object(), redis=Redis(), config=Config(), clock=lambda: now[0])

    def load():
        calls.append(1)
        return {"probability": 0}

    first = service.cached("x", 60, load)
    now[0] += 59
    hit = service.cached("x", 60, load)
    assert hit["fetched_at"] == first["fetched_at"] and hit["cache_status"] == "hit" and len(calls) == 1

    def fail():
        raise RuntimeError()

    now[0] += 2
    stale = service.cached("x", 60, fail)
    assert stale["stale"] and stale["fetched_at"] == first["fetched_at"] and stale["probability"] == 0
    now[0] += 400
    assert service.cached("x", 60, fail)["status"] == "unavailable"
    service.redis = object()
    assert service.cached("y", 60, load)["status"] == "ready"


def test_identical_inflight_request_shared_and_bounded():
    service = LiveService(client=object(), redis=Redis(), config=Config())
    entered, release = threading.Event(), threading.Event()
    calls = []

    def load():
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return {"value": 1}

    with ThreadPoolExecutor(4) as pool:
        first = pool.submit(service.cached, "one", 60, load)
        assert entered.wait(2)
        rest = [pool.submit(service.cached, "one", 60, load) for _ in range(3)]
        release.set()
        assert first.result()["value"] == 1
        assert all(f.result()["value"] == 1 for f in rest)
    assert len(calls) == 1


def test_history_membership_and_lazy_native_window_with_baselines():
    now = 2_000_000
    calls = []

    class Upstream:
        def event(self, event_id):
            return {
                "id": event_id,
                "markets": [
                    {
                        "id": "m",
                        "version": "v2",
                        "outcomes": ["No", "Yes"],
                        "positionIds": ["big", "other"],
                        "outcomePrices": ["0", "1"],
                        "volume": 3,
                        "closed": False,
                    }
                ],
            }

        def history(self, asset, **kwargs):
            calls.append((asset, kwargs))
            if "interval" in kwargs:
                return [dict(timestamp=now, price=0.5, resolution_seconds=0)]
            return [dict(timestamp=kwargs["as_of"], price=0.2, resolution_seconds=300)]

    service = LiveService(client=Upstream(), redis=Redis(), config=Config(), clock=lambda: now)
    service.live("1")
    assert not calls
    result = service.history("1", "m", "big", "1d")
    assert calls[0] == ("big", {"interval": "1d"})
    assert result["changes"]["24h"]["percentage_points"] == 30
    assert len(result["points"]) == 1
    import pytest

    with pytest.raises(ValueError):
        service.history("1", "m", "unrelated", "1d")
    service.history("1", "m", "big", "1d")
    assert len(calls) == 3


def test_history_cache_never_overrides_fresh_closed_status():
    now = [2_000_000]

    class Upstream:
        closed = False

        def event(self, event_id):
            return {
                "id": event_id,
                "markets": [
                    {
                        "id": "m",
                        "version": "v2",
                        "outcomes": ["Yes"],
                        "positionIds": ["1"],
                        "outcomePrices": ["1"],
                        "volume": 3,
                        "closed": self.closed,
                    }
                ],
            }

        def history(self, asset, **kwargs):
            return [dict(timestamp=now[0], price=1, resolution_seconds=0)]

    upstream = Upstream()
    service = LiveService(client=upstream, redis=Redis(), config=Config(), clock=lambda: now[0])
    first = service.history("1", "m", "1", "1w")
    now[0] += 61
    upstream.closed = True
    cached = service.history("1", "m", "1", "1w")
    assert cached["cache_status"] == "hit" and cached["fetched_at"] == first["fetched_at"]
    assert cached["closed"] and cached["changes"]["24h"]["reason"] == "closed_or_resolved"
