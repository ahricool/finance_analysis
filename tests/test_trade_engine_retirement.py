"""Trade Engine retirement removes only engine history and keeps real holdings."""

import importlib.util
import io
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from finance_analysis.core.paths import clear_paths_cache
from finance_analysis.database.base import Base


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0087_retire_trade_engine.py"
    spec = importlib.util.spec_from_file_location("retire_trade_engine", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=("sqlite", "postgresql"))
def connection(request):
    url = "sqlite://" if request.param == "sqlite" else os.getenv("STOCK_RETIREMENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("STOCK_RETIREMENT_TEST_DATABASE_URL must point to an isolated test database")
    engine = sa.create_engine(url)
    schema = "retire_trade_engine_" + uuid4().hex
    try:
        with engine.begin() as conn:
            if request.param == "postgresql":
                conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
                conn.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
            yield conn
            if request.param == "postgresql":
                conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        engine.dispose()


def test_engine_entrypoints_are_absent_and_holdings_remain():
    from finance_analysis.interfaces.api.v1.router import router
    from finance_analysis.tasks.celery.app import celery_app
    from finance_analysis.tasks.celery.schedule import (
        build_beat_schedule,
        build_task_routes,
        get_scheduled_task_definition,
    )
    from finance_analysis.database import models

    celery_app.loader.import_default_modules()
    for job in ("trade_engine_cn", "trade_engine_us"):
        assert get_scheduled_task_definition(job) is None
        assert f"scheduled.{job}" not in celery_app.tasks
        assert f"scheduled.{job}" not in build_task_routes()
        assert not any(row["task"] == f"scheduled.{job}" for row in build_beat_schedule().values())
    assert not {"trade_signal", "trade_llm_state"}.intersection(Base.metadata.tables)
    assert "trade_engine_enabled" not in models.PortfolioPosition.__table__.columns
    assert not hasattr(models, "TradeLLMState")
    assert not hasattr(models, "TradeSignalRow")
    assert not any("/trade-engine" in route.path for route in router.routes)
    assert not any(
        "PATCH" in getattr(route, "methods", set()) and "/holdings/positions/" in route.path
        for route in router.routes
    )
    assert any(route.path.endswith("/holdings/buy") for route in router.routes)
    assert any(route.path.endswith("/holdings/sell") for route in router.routes)
    root = Path(__file__).resolve().parents[1] / "src/finance_analysis"
    assert not list((root / "trade_engine").rglob("*.py"))
    assert not list((root / "tasks/celery/jobs/trade_engine").rglob("*.py"))
    for job in ("analysis_a_share_pre_close_review", "analysis_us_postmarket_review", "market_calendar"):
        assert f"scheduled.{job}" in celery_app.tasks


@pytest.mark.parametrize("custom_audit", (False, True))
def test_history_cleanup_preserves_holdings_operations_and_unrelated_messages(
    connection, monkeypatch, tmp_path, custom_audit
):
    module = migration()
    monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    clear_paths_cache()
    root = tmp_path / "data/logs"
    (root / "celery").mkdir(parents=True)
    cn_log = root / "celery/A股交易引擎_old.log"
    us_log = root / "celery/scheduled.trade_engine_us_old.log"
    recorded = root / "celery/custom-engine.log"
    unrelated = root / "celery/持仓复核_keep.log"
    outside = tmp_path / "outside.log"
    for path in (cn_log, us_log, recorded, unrelated, outside):
        path.write_text("keep" if path in (unrelated, outside) else "engine")
    audit = tmp_path / "custom-audit" if custom_audit else root / "llm"
    if custom_audit:
        monkeypatch.setenv("LLM_LOG_DIR", str(audit))
    else:
        monkeypatch.delenv("LLM_LOG_DIR", raising=False)
    audit.mkdir()
    audit_file = audit / "attempts.log"
    kept = b'{"call_type":"a_share_pre_close_review"}\ninvalid line\n'
    audit_file.write_bytes(b'{"call_type":"trade_engine_market","prompt":"retired"}\n' + kept)
    metadata = sa.MetaData()
    tasks = sa.Table("task", metadata, sa.Column("id", sa.Integer, primary_key=True),
                     sa.Column("task_type", sa.String), sa.Column("scheduler_job_id", sa.String),
                     sa.Column("task_log", sa.String))
    messages = sa.Table("notification", metadata, sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("title", sa.String), sa.Column("route_type", sa.String),
                        sa.Column("content", sa.Text))
    usage = sa.Table("llm_usage", metadata, sa.Column("id", sa.Integer, primary_key=True),
                     sa.Column("call_type", sa.String))
    positions = sa.Table("portfolio_position", metadata, sa.Column("id", sa.Integer, primary_key=True),
                         sa.Column("quantity", sa.Integer), sa.Column("trade_engine_enabled", sa.Boolean))
    receipts = sa.Table("portfolio_mutation", metadata, sa.Column("uid", sa.Integer, primary_key=True),
                        sa.Column("operation_id", sa.String, primary_key=True),
                        sa.Column("request_hash", sa.String), sa.Column("response_json", sa.Text))
    signals = sa.Table("trade_signal", metadata, sa.Column("id", sa.Integer, primary_key=True),
                       sa.Column("notification_id", sa.Integer))
    state = sa.Table("trade_llm_state", metadata, sa.Column("id", sa.Integer, primary_key=True))
    preserved = ("portfolio_account", "position_lot", "trade_operation", "cash_operation", "finance_events")
    for name in preserved:
        sa.Table(name, metadata, sa.Column("id", sa.Integer, primary_key=True))
    metadata.create_all(connection)
    connection.execute(tasks.insert(), [
        dict(id=1, task_type=module.TASK_TYPES[0], scheduler_job_id=None, task_log=str(recorded)),
        dict(id=2, task_type=module.TASK_TYPES[1], scheduler_job_id=None, task_log="../../outside.log"),
        dict(id=3, task_type="legacy", scheduler_job_id=module.JOB_IDS[1], task_log=None),
        dict(id=4, task_type="scheduled_a_share_pre_close_review", scheduler_job_id=None, task_log=str(unrelated)),
    ])
    connection.execute(messages.insert(), [
        dict(id=1, title="交易引擎", route_type="alert", content="retired"),
        dict(id=2, title="renamed", route_type="alert", content="linked engine history"),
        dict(id=3, title="error", route_type="system_error", content=f"\n- 类型：{module.TASK_TYPES[0]}\nretired"),
        dict(id=4, title="error", route_type="system_error", content=f"\n- 类型：{module.TASK_TYPES[1]}\nretired"),
        dict(id=5, title="持仓复核", route_type="report", content="keep"),
        dict(id=6, title="error", route_type="system_error", content="\n- 类型：scheduled_market_calendar\nkeep"),
        dict(id=7, title="交易引擎", route_type="report", content="unrelated report title"),
    ])
    connection.execute(usage.insert(), [dict(id=1, call_type=module.CALL_TYPE), dict(id=2, call_type="signal_center")])
    connection.execute(positions.insert(), [dict(id=11, quantity=100, trade_engine_enabled=False)])
    original = {"id": 11, "quantity": "100", "trade_engine_enabled": False, "lots": [{"role": "CORE"}]}
    connection.execute(receipts.insert(), [
        dict(uid=1, operation_id="buy", request_hash="unchanged", response_json=json.dumps(original)),
        dict(uid=1, operation_id="invalid", request_hash="keep", response_json="invalid json"),
        dict(uid=1, operation_id="cash", request_hash="keep", response_json='{"cash":"100"}'),
    ])
    connection.execute(signals.insert(), dict(id=1, notification_id=2))
    connection.execute(state.insert(), dict(id=1))
    for name in preserved:
        connection.execute(metadata.tables[name].insert().values(id=1))
    try:
        module.upgrade()
        module.upgrade()
        inspector = sa.inspect(connection)
        assert not {"trade_signal", "trade_llm_state"}.intersection(inspector.get_table_names())
        assert {row["name"] for row in inspector.get_columns("portfolio_position")} == {"id", "quantity"}
        assert connection.scalar(sa.select(positions.c.quantity)) == 100
        for name in preserved:
            assert connection.scalar(sa.select(sa.func.count()).select_from(metadata.tables[name])) == 1
        assert connection.scalars(sa.select(tasks.c.id)).all() == [4]
        assert connection.scalars(sa.select(messages.c.id).order_by(messages.c.id)).all() == [5, 6, 7]
        assert connection.scalars(sa.select(usage.c.call_type)).all() == ["signal_center"]
        result = connection.execute(sa.select(receipts).where(receipts.c.operation_id == "buy")).mappings().one()
        assert result["request_hash"] == "unchanged"
        del original["trade_engine_enabled"]
        assert json.loads(result["response_json"]) == original
        assert connection.scalar(
            sa.select(receipts.c.response_json).where(receipts.c.operation_id == "invalid")
        ) == "invalid json"
        assert connection.scalar(sa.select(sa.func.count()).select_from(receipts)) == 3
        assert not any(path.exists() for path in (cn_log, us_log, recorded))
        assert unrelated.read_text() == outside.read_text() == "keep"
        assert audit_file.read_bytes() == kept
        with pytest.raises(RuntimeError, match="irreversible"):
            module.downgrade()
    finally:
        clear_paths_cache()


def test_empty_or_partial_schema_can_upgrade_twice(connection, monkeypatch, tmp_path):
    module = migration()
    module.op = Operations(MigrationContext.configure(connection))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    clear_paths_cache()
    try:
        module.upgrade()
        connection.execute(sa.text("CREATE TABLE trade_llm_state (id INTEGER PRIMARY KEY)"))
        module.upgrade()
        assert "trade_llm_state" not in sa.inspect(connection).get_table_names()
    finally:
        clear_paths_cache()


def test_offline_sql_removes_engine_history_without_dropping_portfolio():
    module = migration()
    output = io.StringIO()
    module.op = Operations(MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    ))
    module.upgrade()
    sql = output.getvalue()
    assert "DROP TABLE IF EXISTS trade_signal" in sql
    assert "DROP TABLE IF EXISTS trade_llm_state" in sql
    assert "DROP COLUMN IF EXISTS trade_engine_enabled" in sql
    assert "DELETE FROM notification" in sql
    assert "UPDATE portfolio_mutation" in sql
    for name in ("portfolio_account", "portfolio_position", "position_lot", "trade_operation", "portfolio_mutation"):
        assert f"DROP TABLE {name}" not in sql
        assert f"DELETE FROM {name}" not in sql


def test_real_legacy_schema_upgrade_preserves_typed_receipt_replay(connection, monkeypatch, tmp_path):
    if connection.dialect.name != "postgresql":
        pytest.skip("The legacy migration uses PostgreSQL JSONB")
    from sqlalchemy.orm import Session

    from finance_analysis.database.models.portfolio import PortfolioMutation, PortfolioPosition, TradeOperation
    from finance_analysis.database.models.stock import Instrument
    from finance_analysis.database.repositories.portfolio import PortfolioRepository
    from finance_analysis.portfolio.receipts import decode_receipt
    from finance_analysis.portfolio.service import PortfolioService

    root = Path(__file__).resolve().parents[1]
    for filename in ("0062_holdings_portfolio_risk", "0063_portfolio_mutation"):
        spec = importlib.util.spec_from_file_location(filename, root / f"alembic/versions/{filename}.py")
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        legacy.op = Operations(MigrationContext.configure(connection))
        legacy.upgrade()
    Instrument.__table__.create(connection)
    connection.execute(Instrument.__table__.insert().values(
        code="600519.SH", market="CN", native_code="600519", name="Test", instrument_type="STOCK",
        currency="CNY", source="MANUAL",
    ))

    class Database:
        @contextmanager
        def get_session(self):
            with Session(connection, join_transaction_mode="create_savepoint") as session:
                yield session

        def _run_write_transaction(self, name, write):
            with self.get_session() as session, session.begin():
                return write(session)

    service = PortfolioService(PortfolioRepository(Database()))
    account = next(item for item in service.ensure_accounts(1) if item["market"] == "CN")
    service.set_cash(1, account_id=account["id"], amount="100000")
    operation_id = str(uuid4())
    kwargs = dict(account_id=account["id"], symbol="600519.SH", quantity="100", price="10",
                  executed_at=datetime(2026, 10, 30, 2, tzinfo=timezone.utc), operation_id=operation_id)
    original = service.buy(1, **kwargs)
    receipt = PortfolioMutation.__table__
    where = (receipt.c.uid == 1, receipt.c.operation_id == operation_id)
    row = connection.execute(sa.select(receipt).where(*where)).mappings().one()
    legacy_payload = json.loads(row["response_json"])
    legacy_payload["trade_engine_enabled"] = False
    connection.execute(receipt.update().where(*where).values(response_json=json.dumps(legacy_payload)))
    assert decode_receipt(json.dumps(legacy_payload))["quantity"] == Decimal("100")
    module = migration()
    module.op = Operations(MigrationContext.configure(connection))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    clear_paths_cache()
    try:
        module.upgrade()
        replayed = service.buy(1, **kwargs)
        assert replayed == original
        assert isinstance(replayed["quantity"], Decimal)
        assert isinstance(replayed["opened_at"], datetime)
        assert connection.scalar(sa.select(PortfolioPosition.quantity)) == Decimal("100")
        assert connection.scalar(sa.select(sa.func.count()).select_from(TradeOperation)) == 1
        assert connection.scalar(sa.select(receipt.c.request_hash).where(*where)) == row["request_hash"]
        assert service.list_accounts(1, market="CN")[0]["cash"] == Decimal("100000")
        columns = {column["name"] for column in sa.inspect(connection).get_columns("portfolio_position")}
        assert "trade_engine_enabled" not in columns
    finally:
        clear_paths_cache()
