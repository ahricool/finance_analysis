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
        assert client.get("/api/v1/crypto/btc/strategies/unknown/overview").status_code == 404
        definitions = client.get("/api/v1/crypto/btc/strategies").json()
        assert definitions[0]["strategy_key"] == "btc_breakout_v1"
        summaries = client.get("/api/v1/crypto/btc/strategies/performance").json()
        assert len(summaries) == 1 and "equity_curve" not in summaries[0]
        assert (
            client.get("/api/v1/crypto/btc/strategies/btc_breakout_v1/overview").json()
            == client.get("/api/v1/crypto/btc/overview").json()
        )
        stats = client.get("/api/v1/crypto/btc/performance").json()
        assert stats["current_position"]["position_pct"] == "0"
        assert stats["performance_start_at"] is None and stats["equity_curve"] == []
        assert client.get("/api/v1/crypto/btc/signals?start=2026-09-01").status_code == 422


def test_rest_uses_existing_cookie_auth_middleware():
    from finance_analysis.interfaces.api.middlewares.auth import AuthMiddleware

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(crypto.router, prefix="/api/v1/crypto")
    with TestClient(app) as client:
        for endpoint in ("overview", "signals", "performance"):
            assert client.get("/api/v1/crypto/btc/" + endpoint).status_code == 401


def test_performance_serializes_complete_cycles_and_range_markers(repository):
    from decimal import Decimal as D

    from finance_analysis.crypto.position import change_position
    from finance_analysis.crypto.strategy import evaluate

    from .helpers import candle

    for index, target in enumerate((D(1), D(1), D(0))):
        bar = candle(index)

        def calculate(state):
            _, snapshot = evaluate([bar], [], bar.close_time, state)
            after = change_position(state, target, bar.close, bar.close_time)
            snapshot.update(
                action="BUY" if index == 0 else "EXIT" if index == 2 else "HOLD",
                position_before=state.position_pct,
                position_after=target,
                position_delta=target - state.position_pct,
                average_entry_price=after.average_entry_price,
                position_state=after.position_state,
            )
            return after, snapshot

        repository.evaluate_once("btc_breakout_v1", "BTCUSDT", bar.close_time, calculate)
    app = FastAPI()
    app.include_router(crypto.router, prefix="/api/v1/crypto")
    app.dependency_overrides[crypto.get_crypto_service] = lambda: CryptoService(repository)
    with TestClient(app) as client:
        stats = client.get("/api/v1/crypto/btc/performance").json()
        assert stats["execution_count"] == 2 and stats["closed_trades"] == 1
        assert stats["win_rate"] == "1"
        assert len(stats["equity_curve"]) == 3 and stats["current_position"]["average_entry_price"] is None
        result = client.get(
            "/api/v1/crypto/btc/signals",
            params={
                "start": candle(0).close_time.isoformat(),
                "end": candle(2).close_time.isoformat(),
                "actions_only": True,
                "limit": 2000,
            },
        ).json()
        assert [item["action"] for item in result["items"]] == ["EXIT", "BUY"]
