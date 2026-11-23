"""Daily forecast scheduling, transport, exchange dates, and atomic persistence."""

import json
import os
import runpy
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from kombu.exceptions import OperationalError
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from finance_analysis.daily_forecast import service
from finance_analysis.daily_forecast.models import DailyForecast, DailyForecastBar
from finance_analysis.database.models.stock import Instrument, StockDaily
from finance_analysis.database.repositories.daily_forecast import DailyForecastRepository
from finance_analysis.market_review.trading_calendar import get_trading_days_between, get_upcoming_trading_days
from finance_analysis.tasks.celery.jobs.market_data_sync import tasks


AS_OF = date(2026, 11, 25)


def _history():
    dates = get_trading_days_between("us", date(2026, 11, 1), AS_OF)[-15:]
    return [SimpleNamespace(date=day, open=100, high=105, low=99, close=103, volume=5, amount=None) for day in dates]


def _response(request):
    payload = json.loads(request.content)
    window, = payload["windows"]
    return {
        "protocol": 1, "model": "small", "weights_revision": "fixed",
        "predictions": [{"symbol": window["symbol"], "bars": [
            {"timestamp": stamp, "open": 102, "high": 106, "low": 99, "close": 104}
            for stamp in window["targets"]
        ]}],
    }


def test_daily_forecast_only_uses_closed_histories_and_skips_holidays(monkeypatch):
    rows = _history()
    repo = Mock()
    repo.histories.return_value = {"AAPL.US": rows, "SHORT.US": rows[1:], "STALE.US": rows[:-1] + rows[-2:-1]}
    valid_request = runpy.run_path(str(Path(__file__).parents[1] / "kronos_worker/server.py"))["Request"]
    attempts = []

    def transport(request):
        payload = json.loads(request.content)
        attempts.append(payload)
        assert request.url.path == "/predict"
        wire = valid_request.model_validate(payload)
        assert wire.interval == "1d"
        assert len(wire.windows[0].bars) == 15
        with pytest.raises(ValidationError):
            valid_request.model_validate({"protocol": 1, "windows": payload["windows"]})
        if len(attempts) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=_response(request))

    client = httpx.Client(transport=httpx.MockTransport(transport), base_url="http://kronos")
    monkeypatch.setattr(service.httpx, "Client", lambda **_: client)
    monkeypatch.setattr(service, "sleep", lambda _: None)
    result = service.run_daily_forecast("US", AS_OF, [1, 2, 3], "http://kronos", "small", repo)
    assert len(attempts) == 2
    assert result["eligible_symbols"] == result["predicted_symbols"] == 1
    market, anchor, forecasts = repo.replace_market.call_args.args
    assert (market, anchor) == ("US", AS_OF)
    prediction, = forecasts
    assert prediction.symbol == "AAPL.US"
    assert prediction.anchor_close == 103
    assert len(prediction.bars) == 10
    assert [bar.trade_date for bar in prediction.bars[:2]] == [date(2026, 11, 27), date(2026, 11, 30)]


def test_failed_batch_keeps_previous_snapshot(monkeypatch):
    repo = Mock()
    rows = _history()
    earlier = SimpleNamespace(**(vars(rows[0]) | {"date": rows[0].date - timedelta(days=1)}))
    repo.histories.return_value = {"MSFT.US": rows, "AAPL.US": [earlier, *rows]}
    attempts = []

    def transport(request):
        attempts.append(request)
        return httpx.Response(200, json=_response(request)) if len(attempts) == 1 else httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(transport), base_url="http://kronos")
    monkeypatch.setattr(service.httpx, "Client", lambda **_: client)
    monkeypatch.setattr(service, "sleep", lambda _: None)
    with pytest.raises(httpx.HTTPStatusError):
        service.run_daily_forecast("US", AS_OF, [1, 2], "http://kronos", "small", repo)
    assert len(attempts) == 2
    repo.replace_market.assert_not_called()


def test_calendar_returns_only_known_sessions_at_calendar_boundary(monkeypatch):
    from finance_analysis.market_review import trading_calendar

    sessions = trading_calendar.xcals.get_calendar("XSHG").sessions
    assert get_upcoming_trading_days("cn", sessions[-2].date(), 10) == [sessions[-1].date()]
    assert get_upcoming_trading_days("cn", sessions[-1].date(), 10) == []
    monkeypatch.setattr(trading_calendar, "_XCALS_AVAILABLE", False)
    assert get_upcoming_trading_days("cn", AS_OF, 10) == []


def test_sync_dispatches_after_writes_for_a_partial_sync(monkeypatch):
    events = []
    summary = {"trade_date": AS_OF.isoformat(), "sync_status": "partial"}
    monkeypatch.setattr(tasks, "forecast_url", lambda: "http://kronos")
    monkeypatch.setattr(tasks, "MarketDataSyncService", lambda **_: SimpleNamespace(
        run=lambda: events.append("sync") or summary,
    ))
    monkeypatch.setattr(tasks.forecast_daily_market, "delay", lambda market, day: (
        events.append((market, day)) or SimpleNamespace(id="forecast-id")
    ))
    assert tasks._sync_and_dispatch("US", "full")["kronos_forecast_task_id"] == "forecast-id"
    assert events == ["sync", ("US", AS_OF.isoformat())]

    failure = Mock(side_effect=OperationalError("broker unavailable"))
    monkeypatch.setattr(tasks.forecast_daily_market, "delay", failure)
    assert tasks._sync_and_dispatch("US", "full")["kronos_forecast_dispatch_failed"]
    monkeypatch.setattr(tasks, "MarketDataSyncService", Mock(side_effect=tasks.MarketDataSyncError("failed")))
    with pytest.raises(tasks.MarketDataSyncError):
        tasks._sync_and_dispatch("US", "full")
    failure.assert_called_once()


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_latest_only_migration_and_market_replacement(backend):
    url = "sqlite://" if backend == "sqlite" else os.getenv("PREVIEW_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Requires an isolated PREVIEW_TEST_POSTGRES_URL")
    engine = create_engine(url)
    with engine.connect() as conn, conn.begin():
        if backend == "postgres":
            schema = f"kronos_{uuid4().hex}"
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        migration = runpy.run_path(
            str(Path(__file__).parents[1] / "alembic/versions/0094_daily_kronos_forecast.py"),
        )
        operations = Operations(MigrationContext.configure(conn))
        migration["upgrade"].__globals__["op"] = operations
        migration["upgrade"]()
        assert inspect(conn).has_table("daily_forecast_snapshot")

        @contextmanager
        def session_scope():
            with Session(conn, join_transaction_mode="create_savepoint") as session, session.begin():
                yield session

        repo = DailyForecastRepository(SimpleNamespace(
            session_scope=session_scope, get_session=lambda: Session(conn, join_transaction_mode="create_savepoint"),
        ))
        forecast = DailyForecast(
            symbol="AAPL.US", anchor_date=AS_OF, anchor_close=103, model="small", weights_revision="fixed",
            generated_at=datetime(2026, 11, 26, tzinfo=timezone.utc), lookback=240,
            bars=[DailyForecastBar(trade_date=date(2026, 11, 27), open=100, high=105, low=99, close=102)],
        )
        assert repo.replace_market("US", AS_OF, [forecast])
        assert repo.replace_market("CN", AS_OF, [forecast.model_copy(update={"symbol": "600000.SH"})])
        updated = forecast.model_copy(update={"symbol": "MSFT.US", "anchor_date": date(2026, 11, 26)})
        with pytest.raises(IntegrityError):
            repo.replace_market("US", updated.anchor_date, [updated, updated])
        assert repo.latest("US", "AAPL.US").bars == forecast.bars
        assert repo.replace_market("US", updated.anchor_date, [updated])
        assert not repo.replace_market("US", AS_OF, [forecast])
        assert repo.latest("US", "AAPL.US") is None
        assert repo.latest("US", "MSFT.US").anchor_date == updated.anchor_date
        assert repo.latest("CN", "600000.SH").symbol == "600000.SH"

        if backend == "postgres":
            Instrument.__table__.create(conn)
            StockDaily.__table__.create(conn)
            conn.execute(Instrument.__table__.insert(), [{
                "id": 1, "market": "US", "code": "MSFT.US", "native_code": "MSFT", "name": "Microsoft",
                "instrument_type": "STOCK", "currency": "USD", "source": "TEST",
            }])
            conn.execute(StockDaily.__table__.insert(), [
                {"instrument_id": 1, "date": row.date, "open": row.open, "high": row.high, "low": row.low,
                 "close": row.close, "volume": row.volume, "data_source": "TEST"} for row in _history()
            ])
            rows = repo.histories("US", [1], AS_OF, 3)["MSFT.US"]
            assert [row.date for row in rows] == [row.date for row in _history()[-3:]]
        migration["downgrade"]()
        assert not inspect(conn).has_table("daily_forecast_snapshot")
        if backend == "postgres":
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
    engine.dispose()
