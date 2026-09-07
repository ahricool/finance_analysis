from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.crypto.service import CryptoService
from finance_analysis.interfaces.api.v1.endpoints import crypto
from .helpers import candle


def test_rest_contracts_and_invalid_interval(repository):
    app = FastAPI()
    app.include_router(crypto.router, prefix="/api/v1/crypto")
    service = CryptoService(repository)
    row = candle()
    repository.upsert_klines([row])
    app.dependency_overrides[crypto.get_crypto_service] = lambda: service
    with TestClient(app) as client:
        response = client.get("/api/v1/crypto/btc/klines").json()["items"][0]
        assert response["volume"] == "1.123456789012" and response["closed"] is True
        assert response["open_time"].endswith("Z")
        assert client.get("/api/v1/crypto/btc/klines?interval=15m").status_code == 422
        assert client.get("/api/v1/crypto/btc/klines?limit=1001").status_code == 422
        assert client.get("/api/v1/crypto/btc/overview").json()["state"]["position_state"] == "FLAT"
        assert client.get("/api/v1/crypto/btc/signals").json() == {"items": []}
        assert client.get("/api/v1/crypto/btc/status").json()["ready"] is False


def test_ws_rejects_missing_session_before_market_access(monkeypatch):
    app = FastAPI()
    app.include_router(crypto.router, prefix="/api/v1/crypto")
    monkeypatch.setattr(crypto, "_valid_user", lambda token: False)
    with TestClient(app) as client, client.websocket_connect("/api/v1/crypto/ws") as ws:
        assert ws.receive()["code"] == 4401


def test_rest_uses_existing_cookie_auth_middleware():
    from finance_analysis.interfaces.api.middlewares.auth import AuthMiddleware

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(crypto.router, prefix="/api/v1/crypto")
    with TestClient(app) as client:
        for endpoint in ("overview", "klines", "signals", "status"):
            assert client.get("/api/v1/crypto/btc/" + endpoint).status_code == 401
