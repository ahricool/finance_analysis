from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.crypto.service import CryptoService
from finance_analysis.interfaces.api.v1.endpoints import crypto


def test_rest_contracts_and_invalid_interval(repository):
    app = FastAPI()
    app.include_router(crypto.router, prefix="/api/v1/crypto")
    service = CryptoService(repository)
    app.dependency_overrides[crypto.get_crypto_service] = lambda: service
    with TestClient(app) as client:
        assert client.get("/api/v1/crypto/btc/klines").status_code == 404
        assert client.get("/api/v1/crypto/btc/status").status_code == 404
        assert "market" not in client.get("/api/v1/crypto/btc/overview").json()
        assert client.get("/api/v1/crypto/btc/overview").json()["state"]["position_state"] == "FLAT"
        assert client.get("/api/v1/crypto/btc/signals").json() == {"items": []}


def test_rest_uses_existing_cookie_auth_middleware():
    from finance_analysis.interfaces.api.middlewares.auth import AuthMiddleware

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(crypto.router, prefix="/api/v1/crypto")
    with TestClient(app) as client:
        for endpoint in ("overview", "signals"):
            assert client.get("/api/v1/crypto/btc/" + endpoint).status_code == 401
