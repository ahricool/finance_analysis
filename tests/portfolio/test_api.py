"""Holdings HTTP cash replacement and instrument validation contracts."""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.interfaces.api.v1.endpoints import holdings
from tests.portfolio.test_service import _service


@pytest.fixture
def client(monkeypatch):
    service = _service()
    account = next(item for item in service.ensure_accounts(3) if item["market"] == "CN")
    app = FastAPI()
    app.include_router(holdings.router, prefix="/holdings")
    app.dependency_overrides[holdings.require_current_user] = lambda: None
    app.dependency_overrides[holdings._portfolio] = lambda: service
    monkeypatch.setattr(holdings, "get_effective_uid", lambda request: 3)
    with TestClient(app) as http:
        yield http, account["id"]


def test_cash_replacement_and_removed_deposit_withdraw(client):
    http, account_id = client
    for value in ["100.25", "50", "0"]:
        response = http.patch("/holdings/cash", json={"operation_id": str(uuid4()), "account_id": account_id, "amount": value})
        assert response.status_code == 200
        assert response.json()["cash"] == value
        assert response.headers["cache-control"] == "private, no-store"
    for route in ["deposit", "withdraw"]:
        assert http.post(f"/holdings/cash/{route}", json={"account_id": account_id, "amount": "10"}).status_code == 404


def test_invalid_cash_and_account_rejected(client):
    http, account_id = client
    for payload in [{"account_id": account_id, "amount": "-1"}, {"account_id": account_id, "amount": "NaN"},
                    {"account_id": 999, "amount": "100"}]:
        assert http.patch("/holdings/cash", json={"operation_id": str(uuid4()), **payload}).status_code == 400


def test_buy_checks_instrument_and_uses_master_type(client):
    http, account_id = client
    body = {"account_id": account_id, "quantity": "100", "price": "4"}
    response = http.post("/holdings/buy", json={"operation_id": str(uuid4()), **body, "symbol": "510300.SH"})
    assert response.status_code == 200
    assert response.json()["asset_type"] == "ETF"
    assert http.post("/holdings/buy", json={"operation_id": str(uuid4()), **body, "symbol": "999999.SH"}).status_code == 400


def test_api_requires_valid_key_and_returns_conflict_for_changed_request(client):
    http, account_id = client
    payload = {"account_id": account_id, "symbol": "600519.SH", "quantity": "1", "price": "4"}
    assert http.post("/holdings/buy", json=payload).status_code == 422
    assert http.post("/holdings/buy", json={**payload, "operation_id": "bad"}).status_code == 422
    payload["operation_id"] = str(uuid4())
    first = http.post("/holdings/buy", json=payload)
    assert first.status_code == 200
    assert http.post("/holdings/buy", json=payload).json() == first.json()
    assert http.post("/holdings/buy", json={**payload, "quantity": "2"}).status_code == 409
    assert http.patch("/holdings/cash", json={"account_id": account_id, "amount": "0",
                                           "operation_id": payload["operation_id"]}).status_code == 409
