"""Service to repository to latest API. Uses SQLite locally; live DB when reachable."""  # pragma: allowlist secret

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from finance_analysis.database.models.holdings import HoldingSource, PositionRiskState, RiskEvent  # pragma: allowlist secret
from finance_analysis.database.repositories.holdings import HoldingsRepository, RiskEventRepository  # pragma: allowlist secret
from finance_analysis.portfolio_risk.account import AccountView, apply_account_constraints, merge_account_targets  # pragma: allowlist secret
from finance_analysis.portfolio_risk.config import RiskPolicy  # pragma: allowlist secret
from finance_analysis.portfolio_risk.exits import LegInput, PositionInput, PositionState, QuoteView, evaluate_position_exit  # pragma: allowlist secret
from finance_analysis.portfolio_risk.service import PortfolioRiskService  # pragma: allowlist secret
from finance_analysis.holdings.models import HoldingsSnapshot, ParsedLeg, ParsedPosition  # pragma: allowlist secret


class SqliteDb:
    def __init__(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        with self.engine.begin() as connection:
            for table in (HoldingSource.__table__, PositionRiskState.__table__, RiskEvent.__table__):
                ddl = str(CreateTable(table).compile(dialect=sqlite_dialect.dialect()))
                connection.execute(text(ddl.replace("BIGINT", "INTEGER")))
        self._SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._initialized = True

    def get_session(self) -> Session:
        return self._SessionLocal()

    def _run_write_transaction(self, operation_name, write_operation):
        session = self.get_session()
        try:
            result = write_operation(session)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def session_scope(self):
        from contextlib import contextmanager

        @contextmanager
        def scoped():
            session = self.get_session()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        return scoped()


def test_account_constraint_event_reaches_summary_shape():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc)
    position = PositionInput(
        "a1",
        "p1",
        "600519.SH",
        (LegInput("core", "CORE", Decimal("1000"), Decimal("20"), now),),
    )
    quote = QuoteView(price=Decimal("20"), quote_as_of=now, valid=True)
    computed = evaluate_position_exit(
        position, quote=quote, bars=[], state=PositionState(), policy=RiskPolicy(), now=now, market="CN"
    )
    risks = apply_account_constraints(
        account=AccountView("a1", "CNY", Decimal("100000"), True),
        positions=[(position, computed, quote)],
        policy=RiskPolicy(),
        currencies={"600519.SH": "CNY"},
    )
    merged = merge_account_targets(position, computed, risks[("a1", "p1")])
    assert merged.position_target == Decimal("500")
    assert merged.plan.status == "PENDING"
    assert merged.plan.action == "REDUCE"
    assert Decimal(merged.plan.reduce_quantity) == Decimal("500")
    assert any(event["event_type"] == "ACCOUNT_CONSTRAINT" for event in merged.events)


def test_holdings_migration_revision_is_single_head():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["0063_holdings_published_snapshot"]
    revision = script.get_revision("0063_holdings_published_snapshot")
    assert revision.down_revision == "0062_holdings_portfolio_risk"


def test_repository_json_txn_dedupe_and_latest_api():
    db = SqliteDb()
    sources = HoldingsRepository(db)
    events = RiskEventRepository(db)
    source = sources.get_or_create(1, defaults={"enabled": True, "auth_status": "CONNECTED", "risk_policy": {}})
    published = sources.publish_generation(
        source_id=source.id,
        uid=1,
        expected_config_version=source.config_version,
        expected_generation=source.published_generation,
        new_generation=2,
        content_hash="abc",
        sync_status="OK",
        published_snapshot={"uid": 1, "source_id": source.id, "generation": 2, "content_hash": "abc"},
    )
    assert published is not None
    assert published.published_snapshot["generation"] == 2

    with db.session_scope() as session:
        session.add(
            PositionRiskState(
                uid=1,
                source_id=source.id,
                account_id="a1",
                position_id="p1",
                symbol="600519.SH",
                canonical_symbol="600519.SH",
                plan_status="PENDING",
                plan_action="REDUCE",
                plan_revision=2,
                active_plan={
                    "schema_version": "active_plan.v1",
                    "revision": 2,
                    "status": "PENDING",
                    "action": "REDUCE",
                    "bound_leg_ids": ["core"],
                    "leg_targets": {"core": "500"},
                    "position_target": "500",
                    "current_quantity": "1000",
                    "reduce_quantity": "500",
                    "execution": "UNKNOWN",
                    "hard_locked": False,
                    "needs_review": False,
                },
                legs_state={
                    "schema_version": "legs_state.v1",
                    "episode_consumed": True,
                    "needs_review": False,
                    "five_minute_status": "OK",
                    "quote_status": "OK",
                    "legs": {},
                },
            )
        )
        events.add(
            session,
            uid=1,
            source_id=source.id,
            account_id="a1",
            position_id="p1",
            event_type="ACCOUNT_CONSTRAINT",
            rule_version="v1",
            action="REDUCE",
            dedupe_key="1|a1|p1|ep|2|ACCOUNT_CONSTRAINT",
            target_quantity=Decimal("500"),
            evidence={"five_minute_status": "OK", "quote_status": "OK"},
        )
        assert events.has_dedupe(session, uid=1, dedupe_key="1|a1|p1|ep|2|ACCOUNT_CONSTRAINT")

    with pytest.raises(IntegrityError):
        with db.session_scope() as session:
            events.add(
                session,
                uid=1,
                source_id=source.id,
                account_id="a1",
                position_id="p1",
                event_type="ACCOUNT_CONSTRAINT",
                rule_version="v1",
                action="REDUCE",
                dedupe_key="1|a1|p1|ep|2|ACCOUNT_CONSTRAINT",
            )

    def _insert_conflict(_):
        with db.session_scope() as session:
            events.add(
                session,
                uid=1,
                source_id=source.id,
                account_id="a2",
                position_id="p2",
                event_type="HARD_STOP",
                rule_version="v1",
                action="EXIT",
                dedupe_key="race-key",
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda item: _safe_insert(_insert_conflict, item), range(2)))
    assert sum(1 for item in results if item == "ok") == 1
    assert sum(1 for item in results if item == "conflict") == 1

    service = PortfolioRiskService(holdings=MagicMock(), db=db, market=MagicMock())
    view = service.latest_view(1)
    row = view["positions"][0]
    assert row["five_minute_status"] == "OK"
    assert row["quote_status"] == "OK"
    assert row["current_quantity"] == "1000"
    assert row["active_plan"]["position_target"] == "500"
    assert row["reduce_quantity"] == "500"
    assert row["execution"] == "UNKNOWN"
    assert view["source"]["generation"] == 2

    from finance_analysis.interfaces.api.v1.endpoints import holdings as holdings_ep  # pragma: allowlist secret
    from finance_analysis.interfaces.api.deps import require_current_user  # pragma: allowlist secret

    app = FastAPI()

    @app.middleware("http")
    async def uid_middleware(request, call_next):
        request.state.uid = 1
        return await call_next(request)

    app.include_router(holdings_ep.router, prefix="/api/v1/holdings")
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1, email="t@example.test")
    app.dependency_overrides[holdings_ep._risk] = lambda: service
    with TestClient(app) as client:
        response = client.get("/api/v1/holdings/risk")
    assert response.status_code == 200
    body = response.json()
    assert body["positions"][0]["five_minute_status"] == "OK"
    assert body["positions"][0]["quote_status"] == "OK"
    assert body["positions"][0]["active_plan"]["position_target"] == "500"


def _safe_insert(fn, item):
    try:
        fn(item)
        return "ok"
    except IntegrityError:
        return "conflict"


def test_published_snapshot_migration_on_live_database():  # pragma: allowlist secret
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        pytest.skip("DATABASE_URL is not set")
    engine = create_engine(url)
    try:
        connection = engine.connect()
    except OperationalError as exc:
        pytest.skip(f"live database unavailable: {exc}")  # pragma: allowlist secret
    schema = "holdings_rev_" + uuid.uuid4().hex
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from pathlib import Path
    import importlib.util

    path = Path("alembic/versions/0063_holdings_published_snapshot.py")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        with connection.begin():
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(
                text(
                    "CREATE TABLE holding_source ("
                    "id INTEGER PRIMARY KEY, uid INTEGER NOT NULL, config_version INTEGER NOT NULL DEFAULT 1)"
                )
            )
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()
            columns = {item["name"] for item in inspect(connection).get_columns("holding_source", schema=schema)}
            assert "published_snapshot" in columns
            connection.execute(text("INSERT INTO holding_source (id, uid, published_snapshot) VALUES (1, 1, '{\"generation\": 2}'::jsonb)"))
            value = connection.execute(text("SELECT published_snapshot->>'generation' FROM holding_source WHERE id=1")).scalar_one()
            assert value == "2"
    finally:
        connection.close()
        engine.dispose()


def test_closed_addon_plan_is_persisted_and_returned_by_latest_api():
    db = SqliteDb()
    sources = HoldingsRepository(db)
    source = sources.get_or_create(1, defaults={"enabled": True, "auth_status": "CONNECTED", "risk_policy": {}})
    now = datetime(2026, 9, 16, 6, 0, tzinfo=timezone.utc)
    with db.session_scope() as session:
        session.add(
            PositionRiskState(
                uid=1,
                source_id=source.id,
                account_id="a1",
                position_id="p1",
                symbol="600519.SH",
                canonical_symbol="600519.SH",
                plan_status="PENDING",
                plan_action="REDUCE",
                plan_revision=1,
                episode_id="ep1",
                active_plan={
                    "schema_version": "active_plan.v1",
                    "revision": 1,
                    "status": "PENDING",
                    "action": "REDUCE",
                    "episode_id": "ep1",
                    "bound_leg_ids": ["core", "addon"],
                    "leg_targets": {"core": "1000", "addon": "0"},
                    "position_target": "1000",
                    "current_quantity": "1500",
                    "reduce_quantity": "500",
                    "execution": "UNKNOWN",
                    "hard_locked": False,
                    "needs_review": False,
                },
                legs_state={
                    "schema_version": "legs_state.v1",
                    "episode_consumed": True,
                    "needs_review": False,
                    "five_minute_status": "UNAVAILABLE",
                    "quote_status": "OK",
                    "legs": {},
                },
            )
        )
    entry = datetime(2026, 9, 14, 1, 35, tzinfo=timezone.utc)
    position = ParsedPosition(
        account_id="a1",
        position_id="p1",
        symbol="600519.SH",
        canonical_symbol="600519.SH",
        asset_type="STOCK",
        currency="CNY",
        legs=[
            ParsedLeg(
                account_id="a1",
                position_id="p1",
                leg_id="core",
                leg_role="CORE",
                symbol="600519.SH",
                canonical_symbol="600519.SH",
                asset_type="STOCK",
                quantity=Decimal("1000"),
                entry_price=Decimal("100"),
                entry_time=entry,
                status="OPEN",
                coverage="COVERED",
            ),
            ParsedLeg(
                account_id="a1",
                position_id="p1",
                leg_id="addon",
                leg_role="ADDON",
                symbol="600519.SH",
                canonical_symbol="600519.SH",
                asset_type="STOCK",
                quantity=Decimal("0"),
                entry_price=Decimal("110"),
                entry_time=entry,
                status="CLOSED",
                coverage="COVERED",
            ),
        ],
    )
    snapshot = HoldingsSnapshot(
        uid=1,
        source_id=source.id,
        spreadsheet_id="sheet",
        generation=2,
        content_hash="abc",
        fetched_at=now,
        timezone="Asia/Shanghai",
        status="VALID",
        accounts=[],
        positions=[position],
    )
    service = PortfolioRiskService(holdings=MagicMock(), db=db, market=MagicMock())
    with db.session_scope() as session:
        existing = session.get(PositionRiskState, 1)
        payload = service._compute_position(
            snapshot=snapshot,
            position=position,
            bars=[],
            quote=QuoteView(price=Decimal("108"), quote_as_of=now, valid=True),
            existing=existing,
            policy=RiskPolicy(),
            now=now,
            bars_stale=True,
            latest_expected=None,
            holdings_actionable=True,
        )
        assert payload["computed"] is not None
        assert payload["computed"].plan.status == "SATISFIED_BY_SHEET"
        assert payload["computed"].needs_review is False
        written = service._write_position(
            session,
            snapshot=snapshot,
            position=position,
            existing=existing,
            policy=RiskPolicy(),
            now=now,
            computed=payload["computed"],
            summary=payload["summary"],
        )
        assert written["summary"]["plan_status"] == "SATISFIED_BY_SHEET"
    view = service.latest_view(1)
    assert view["positions"][0]["plan_status"] == "SATISFIED_BY_SHEET"
    assert view["positions"][0]["needs_review"] is False
    from finance_analysis.interfaces.api.v1.endpoints import holdings as holdings_ep  # pragma: allowlist secret
    from finance_analysis.interfaces.api.deps import require_current_user  # pragma: allowlist secret

    app = FastAPI()

    @app.middleware("http")
    async def uid_middleware(request, call_next):
        request.state.uid = 1
        return await call_next(request)

    app.include_router(holdings_ep.router, prefix="/api/v1/holdings")
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1, email="t@example.test")
    app.dependency_overrides[holdings_ep._risk] = lambda: service
    with TestClient(app) as client:
        response = client.get("/api/v1/holdings/risk")
    assert response.status_code == 200
    body = response.json()
    assert body["positions"][0]["plan_status"] == "SATISFIED_BY_SHEET"
    assert body["positions"][0]["needs_review"] is False
