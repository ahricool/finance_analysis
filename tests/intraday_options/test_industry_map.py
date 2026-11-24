from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.endpoints import intraday_options as endpoint
from finance_analysis.intraday_options import industry_map


def test_industry_map_metadata_uses_intraday_universe_and_cached_market_caps(monkeypatch):
    symbols = ("SPY.US", "QQQ.US", "AAPL.US", "NVDA.US", "MISSING.US")
    monkeypatch.setattr(industry_map, "load_universe_symbols", lambda: symbols)
    instruments = Mock()
    instruments.get_by_codes.return_value = {
        "AAPL.US": SimpleNamespace(
            instrument_metadata={"classification": {"sector": "Technology", "industry": "Consumer Electronics"}}
        ),
        "NVDA.US": SimpleNamespace(
            instrument_metadata={"classification": {"sector": "Technology", "industry": "Semiconductors"}}
        ),
    }
    monkeypatch.setattr(industry_map, "InstrumentRepository", lambda: instruments)
    cache = Mock()
    cache.read.return_value = {
        "generated_at": "2026-11-23T20:45:00Z",
        "items": [
            {"code": "AAPL.US", "market_cap": 3e12},
            {"code": "NVDA.US", "market_cap": -1},
            {"code": "OTHER.US", "market_cap": 5e12},
        ],
    }
    monkeypatch.setattr(industry_map, "HeatmapCache", lambda: cache)

    app = FastAPI()
    app.include_router(endpoint.router, prefix="/intraday-options")
    with TestClient(app) as client:
        assert client.get("/intraday-options/industry-map").status_code == 401
        instruments.get_by_codes.assert_not_called()
        app.dependency_overrides[require_current_user] = lambda: object()
        response = client.get("/intraday-options/industry-map")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.json() == {
            "market_cap_as_of": "2026-11-23T20:45:00Z",
            "items": [
                {"symbol": "AAPL.US", "sector": "科技", "industry": "Consumer Electronics", "market_cap": 3e12},
                {"symbol": "NVDA.US", "sector": "科技", "industry": "Semiconductors", "market_cap": None},
                {"symbol": "MISSING.US", "sector": None, "industry": None, "market_cap": None},
            ],
        }
        instruments.get_by_codes.assert_called_once_with(("AAPL.US", "NVDA.US", "MISSING.US"))
        cache.read.assert_called_once_with("US")

        cache.read.side_effect = RedisConnectionError("test redis unavailable")
        fallback = client.get("/intraday-options/industry-map")
        assert fallback.status_code == 200
        assert fallback.json()["market_cap_as_of"] is None
        assert fallback.json()["items"][0] == {
            "symbol": "AAPL.US", "sector": "科技", "industry": "Consumer Electronics", "market_cap": None,
        }
