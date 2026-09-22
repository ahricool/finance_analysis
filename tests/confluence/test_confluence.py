"""Offline scoring, source isolation, dates, atomic publication and HTTP contracts."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from finance_analysis.confluence.engine import aggregate, signal
from finance_analysis.confluence.service import ConfluenceService
from finance_analysis.database.models.confluence import ConfluenceRun, ConfluenceSnapshot
from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.universe import Universe
from finance_analysis.database.models.industry_strength import IndustryStrengthSnapshot, IndustryStrengthConstituent
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot
from finance_analysis.database.models.quant import ModelSignal
from finance_analysis.database.models.dragon_tiger_flow import DragonTigerFlowBatch
from finance_analysis.database.repositories.confluence import ConfluenceRepository
from finance_analysis.interfaces.api.v1.endpoints import confluence as api

DAY = date(2026, 9, 21)
NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


@compiles(JSONB, "sqlite")
def _json_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture
def repo():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    for model in (
        Instrument,
        Universe,
        ConfluenceRun,
        ConfluenceSnapshot,
        IndustryStrengthSnapshot,
        IndustryStrengthConstituent,
        TrendFollowingSnapshot,
        ModelSignal,
        DragonTigerFlowBatch,
    ):
        model.__table__.create(engine)

    class DB:
        @contextmanager
        def get_session(self):
            with Session(engine) as session:
                yield session

        @contextmanager
        def session_scope(self):
            with Session(engine) as session, session.begin():
                yield session

    repository = ConfluenceRepository(DB())
    with repository.db.session_scope() as session:
        session.add(Universe(id=1, key="cn_quant", name="CN", market="CN", universe_type="STRATEGY"))
        session.add(
            Instrument(
                id=1,
                market="CN",
                code="600001.SH",
                name="Stock",
                native_code="600001",
                instrument_type="STOCK",
                currency="CNY",
                source="TEST",
            )
        )
    yield repository
    engine.dispose()


def facts():
    return {
        "industry": dict(
            trade_date=DAY.isoformat(), strength_rank=4, industry_name="行业", state="STRONG", rank_change_3d=8
        ),
        "trend": dict(trade_date=DAY.isoformat(), state="TRENDING", trend_lifecycle="IGNITION", fragility_score=12),
        "quant": dict(trade_date=DAY.isoformat(), universe_rank=3, signal="buy"),
        "etf": None,
        "dragon_tiger": dict(trade_date=DAY.isoformat(), net_inflow=100),
    }


def test_positive_confluence_reasons_and_denominator():
    result = aggregate({key: signal(key, value) for key, value in facts().items()})
    assert result["confluence_score"] == 100
    assert result["available_weight"] == 85
    assert result["positive_signal_count"] == result["available_signal_count"] == 4
    assert result["eligible"] and result["strong_confluence"]
    assert "3D 排名 12 → 4" in " ".join(result["reasons"])
    assert sum(s["score"] or 0 for s in result["signals"].values()) == 85
    for s in result["signals"].values():
        if s["score"] is not None:
            assert f"= {s['score']:g} 分" in s["reasons"][-1]


def test_one_signal_cannot_be_strong_and_missing_is_not_negative():
    inputs = {key: signal(key) for key in facts()}
    inputs["trend"] = signal("trend", facts()["trend"])
    result = aggregate(inputs)
    assert result["confluence_score"] == 100
    assert result["available_weight"] == 30
    assert not result["eligible"] and not result["strong_confluence"]
    assert inputs["dragon_tiger"]["score"] is None
    negative = signal("dragon_tiger", {"net_inflow": -100})
    assert negative["status"] == "negative" and negative["score"] == 0
    inputs["dragon_tiger"] = negative
    assert aggregate(inputs)["confluence_score"] == 75


def test_us_normalization_and_negative_precedence():
    inputs = {key: signal(key) for key in facts()}
    inputs["trend"] = signal("trend", facts()["trend"])
    inputs["quant"] = signal("quant", {"universe_rank": 80, "signal": "hold"})
    result = aggregate(inputs)
    assert result["available_weight"] == 50
    assert result["confluence_score"] == 80
    assert signal("quant", {"universe_rank": 1, "signal": "avoid"})["status"] == "negative"
    assert signal("trend", dict(facts()["trend"], fragility_score=80))["status"] == "negative"
    assert signal("trend", dict(facts()["trend"], state="BROKEN"))["status"] == "negative"


def seed(repo):
    with repo.db.session_scope() as session:
        session.add(
            IndustryStrengthSnapshot(
                trade_date=DAY,
                industry_code="I1",
                industry_name="行业",
                strength_rank=4,
                strength_score=90,
                state="STRONG",
                data_timestamp=NOW,
                members_observed_at=NOW,
                updated_at=NOW,
                quality={},
            )
        )
        session.add(
            IndustryStrengthConstituent(industry_code="I1", stock_code="600001.SH", stock_name="Stock", updated_at=NOW)
        )
        for identifier, day, version, score in [
            (1, DAY, "old", 50),
            (2, DAY, "new", 90),
            (3, DAY + timedelta(days=1), "future", 100),
        ]:
            session.add(
                ModelSignal(
                    id=identifier,
                    trade_date=day,
                    instrument_id=1,
                    code="600001.SH",
                    market="CN",
                    universe_id=1,
                    model_version=version,
                    final_score=score,
                    universe_rank=1,
                    signal="buy",
                    generated_at=NOW + timedelta(minutes=identifier),
                )
            )
            session.add(
                TrendFollowingSnapshot(
                    id=identifier,
                    trade_date=day - timedelta(days=identifier == 1),
                    market="CN",
                    code="600001.SH",
                    instrument_id=1,
                    universe_key="test",
                    market_regime="RISK_ON",
                    market_score=80,
                    rank=10 - identifier,
                    trend_score=80,
                    rs_score=80,
                    breakout_score=80,
                    alpha_score=80,
                    setup="test",
                    state="TRENDING",
                    reference_price=10,
                    atr=1,
                    trend_lifecycle="IGNITION",
                    fragility_score=12,
                    features={"trend_quality": 90},
                )
            )


def test_sources_no_future_and_quant_versions_are_coherent(repo):
    seed(repo)
    trend = repo.trend("CN", DAY)
    quant = repo.quant("CN", DAY)
    assert len(trend) == len(quant) == 1
    assert trend[0]["trade_date"] == quant[0]["trade_date"] == DAY
    assert trend[0]["previous_rank"] == 9
    assert quant[0]["model_version"] == "new"
    assert quant[0]["final_score"] == 90
    assert repo.trend("US", DAY) == []
    assert repo.quant("CN", DAY - timedelta(days=1)) == []


def test_future_current_members_cannot_leak_into_historical_industry(repo):
    seed(repo)
    assert repo.industry("CN", DAY)[0]["industry_code"] == "I1"
    with repo.db.session_scope() as session:
        row = session.scalar(select(IndustryStrengthConstituent))
        row.updated_at = NOW + timedelta(days=1)
    assert repo.industry("CN", DAY) == []
    assert repo.industry("US", DAY) == []
    service = ConfluenceService(repo)
    service.run("CN", DAY)
    row = repo.read("CN", DAY)["items"][0]
    assert row["signals"]["industry"]["status"] == row["signals"]["etf"]["status"] == "unavailable"
    assert service.ranking("CN", DAY)["items"] == []


def test_upsert_partial_source_filtering_and_empty_generation(repo, monkeypatch):
    seed(repo)
    service = ConfluenceService(repo)
    service.run("CN", DAY)
    first = repo.read("CN", DAY)["items"][0]
    assert first["eligible"]
    assert service.ranking("CN", DAY, lifecycle="IGNITION", industry="I1", top_industry=True)["total"] == 1
    assert service.ranking("CN", DAY, strong_only=True)["total"] == 0
    with repo.db.get_session() as session:
        old_id = session.scalar(select(ConfluenceSnapshot.id))
    service.run("CN", DAY)
    with repo.db.get_session() as session:
        assert list(session.scalars(select(ConfluenceSnapshot.id))) == [old_id]
    monkeypatch.setattr(repo, "quant", lambda *_: (_ for _ in ()).throw(RuntimeError("source unavailable")))
    service.run("CN", DAY)
    result = repo.read("CN", DAY)
    assert result["source_availability"]["quant"]["status"] == "failed"
    assert result["items"][0]["available_signal_count"] == 2
    assert result["items"][0]["signals"]["quant"]["status"] == "unavailable"
    assert service.ranking("CN", DAY)["total"] == 0
    assert service.ranking("CN", DAY, min_signals=2)["total"] == 1
    monkeypatch.setattr(repo, "instruments", lambda *_: [])
    service.run("CN", DAY)
    assert repo.read("CN", DAY)["items"] == []
    assert repo.dates("CN") == [DAY]


def test_dragon_recent_native_periods_no_double_count_and_no_future(repo, monkeypatch):
    monkeypatch.setattr(
        "finance_analysis.dragon_tiger_flow.calendar.sessions_through",
        lambda day, count: [day - timedelta(days=i) for i in range(count)],
    )

    def row(period, amount):
        return dict(
            symbol="600001.SH",
            range_days=period,
            concepts=["A", "B"],
            net_value=str(amount),
            buy_value="100",
            sell_value="0",
            org_net_value="10",
            hot_money_net_value=None,
        )

    with repo.db.session_scope() as session:
        for i in (-4, -1, 0, 1):
            session.add(
                DragonTigerFlowBatch(
                    trade_date=DAY + timedelta(days=i),
                    batch_id=str(i),
                    rule_version="v1",
                    collected_at=NOW,
                    generated_at=NOW,
                    payload={"sources": {"all": {"rows": [row(1, -100), row(3, 999)]}}},
                )
            )
    rows = repo.dragon_tiger("CN", DAY)
    assert len(rows) == 1
    assert rows[0]["net_inflow"] == -100
    assert rows[0]["range_days"] == 1
    assert rows[0]["hot_money_net_inflow"] is None
    assert len(rows[0]["records"]) == 4
    assert rows[0]["concept_flows"] == [{"name": "A", "net_inflow": -50}, {"name": "B", "net_inflow": -50}]
    assert signal("dragon_tiger", rows[0])["status"] == "negative"
    assert repo.dragon_tiger("US", DAY) == []


def test_get_api_only_reads_saved_results_and_validates_filters(repo, monkeypatch):
    seed(repo)
    ConfluenceService(repo).run("CN", DAY)

    def forbidden(*args, **kwargs):
        raise AssertionError("GET must not load sources or calculate")

    for name in ("trend", "quant", "industry", "dragon_tiger", "save"):
        monkeypatch.setattr(repo, name, forbidden)
    monkeypatch.setattr(ConfluenceService, "run", forbidden)
    app = FastAPI()
    app.include_router(api.router, prefix="/confluence")
    app.dependency_overrides[api.get_service] = lambda: ConfluenceService(repo)
    app.dependency_overrides[api.require_current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        ranking = client.get("/confluence/ranking").json()
        assert ranking["total"] == 1
        assert ranking["items"][0]["available_weight"] == 75
        assert client.get("/confluence/dates").json() == [DAY.isoformat()]
        assert client.get("/confluence/600001.SH").status_code == 200
        assert client.get("/confluence/600002.SH").status_code == 404
        assert client.get("/confluence/ranking?min_signals=6").status_code == 422
        assert client.get("/confluence/ranking?market=HK").status_code == 422
        assert client.get("/confluence/ranking?trade_date=2020-01-01").json()["items"] == []


def test_migration_upgrade_downgrade_and_metadata_match():
    path = Path(__file__).parents[2] / "alembic/versions/0065_confluence.py"
    spec = importlib.util.spec_from_file_location("confluence_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    rules_spec = importlib.util.spec_from_file_location(
        "rules_migration", Path(__file__).parents[2] / "alembic/versions/0066_confluence_rules.py"
    )
    rules_migration = importlib.util.module_from_spec(rules_spec)
    rules_spec.loader.exec_module(rules_migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        connection.execute(
            text(
                "INSERT INTO confluence_run "
                "(market, trade_date, generated_at, algorithm_version, source_availability) "
                "VALUES ('CN', '2026-09-21', '2026-09-21 12:00:00', 'v1', '{}')"
            )
        )
        rules_migration.op = migration.op
        rules_migration.upgrade()
        assert connection.execute(text("SELECT rules FROM confluence_run")).scalar() is None
        for model in (ConfluenceRun, ConfluenceSnapshot):
            assert {c["name"] for c in inspect(connection).get_columns(model.__tablename__)} == set(
                model.__table__.c.keys()
            )
        assert inspect(connection).get_unique_constraints("confluence_snapshot")[0]["column_names"] == [
            "market",
            "trade_date",
            "instrument_id",
        ]
        rules_migration.downgrade()
        migration.downgrade()
        assert not inspect(connection).get_table_names()


def test_older_generation_cannot_overwrite_newer_and_failed_save_rolls_back(repo):
    manifest = dict(generated_at=NOW, algorithm_version="v1", source_availability={})
    inputs = {key: signal(key, value) for key, value in facts().items()}
    row = dict(instrument_id=1, **aggregate(inputs), generated_at=NOW, algorithm_version="v1")
    assert repo.save("CN", DAY, [row], manifest)
    assert not repo.save("CN", DAY, [], dict(manifest, generated_at=NOW - timedelta(seconds=1)))
    assert len(repo.read("CN", DAY)["items"]) == 1
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        repo.save(
            "CN", DAY, [dict(row, available_signal_count=10)], dict(manifest, generated_at=NOW + timedelta(seconds=1))
        )
    result = repo.read("CN", DAY)
    assert result["items"][0]["available_signal_count"] == 4
    assert result["generated_at"].replace(tzinfo=timezone.utc) == NOW


def test_post_is_admin_only_and_enqueues_without_computing(monkeypatch):
    from fastapi import HTTPException
    from finance_analysis.tasks.celery.jobs.confluence.tasks import run_confluence_cn

    sent = []
    monkeypatch.setattr(run_confluence_cn, "apply_async", lambda **kw: sent.append(kw) or SimpleNamespace(id="job"))
    app = FastAPI()
    app.include_router(api.router, prefix="/confluence")

    def forbidden():
        raise HTTPException(403, "Admin only")

    app.dependency_overrides[api.require_admin] = forbidden
    with TestClient(app) as client:
        assert client.post("/confluence/run", json={"market": "CN"}).status_code == 403
        assert not sent
        app.dependency_overrides[api.require_admin] = lambda: SimpleNamespace(id=7)
        response = client.post("/confluence/run", json={"market": "CN", "trade_date": DAY.isoformat()})
        assert response.status_code == 202 and response.json()["task_id"] == "job"
        assert sent[0]["kwargs"]["_triggered_by_uid"] == 7
        assert sent[0]["queue"] == "analysis"
        assert client.post("/confluence/run", json={"market": "US", "trade_date": "2099-01-01"}).status_code == 422


@pytest.mark.parametrize(
    "action,rank,expected",
    [
        ("buy", 100, "positive"),
        ("watch", 100, "neutral"),
        ("hold", 100, "neutral"),
        ("avoid", 100, "negative"),
        ("avoid", 1, "negative"),
        ("watch", 20, "positive"),
        ("hold", 20, "positive"),
    ],
)
def test_quant_real_contract(action, rank, expected):
    assert signal("quant", {"signal": action, "universe_rank": rank})["status"] == expected


def test_industry_rerun_retains_saved_evidence_after_latest_members_refresh(repo):
    seed(repo)
    service = ConfluenceService(repo)
    service.run("CN", DAY)
    saved = repo.read("CN", DAY)["items"][0]["signals"]["industry"]
    assert saved["status"] == "positive"
    from sqlalchemy import delete

    with repo.db.session_scope() as session:
        session.execute(delete(IndustryStrengthConstituent))
        session.add(
            IndustryStrengthConstituent(
                industry_code="I2", stock_code="600001.SH", stock_name="Stock", updated_at=NOW + timedelta(days=1)
            )
        )
        session.add(
            IndustryStrengthSnapshot(
                trade_date=DAY + timedelta(days=1),
                industry_code="I2",
                industry_name="新行业",
                strength_rank=50,
                state="WEAK",
                data_timestamp=NOW + timedelta(days=1),
                members_observed_at=NOW + timedelta(days=1),
                updated_at=NOW + timedelta(days=1),
                quality={},
            )
        )
        session.scalar(select(ModelSignal).where(ModelSignal.id == 2)).signal = "avoid"
    assert repo.industry("CN", DAY) == []
    assert repo.industry("CN", DAY + timedelta(days=1))[0]["industry_code"] == "I2"
    service.run("CN", DAY)
    result = repo.read("CN", DAY)
    assert result["items"][0]["signals"]["industry"] == saved
    assert result["items"][0]["signals"]["quant"]["status"] == "negative"
    assert result["source_availability"]["industry"]["retained_signal_count"] == 1
    # Even an industry-only historical row must survive rerunning with no rebuildable sources.
    with repo.db.session_scope() as session:
        session.execute(delete(ModelSignal))
        session.execute(delete(TrendFollowingSnapshot))
    service.run("CN", DAY)
    assert repo.read("CN", DAY)["items"][0]["signals"]["industry"] == saved


def test_industry_requires_exact_formal_generation_not_old_members(repo):
    seed(repo)
    with repo.db.session_scope() as session:
        session.scalar(select(IndustryStrengthConstituent)).updated_at = NOW - timedelta(days=1)
    assert repo.industry("CN", DAY) == []
    ConfluenceService(repo).run("CN", DAY)
    assert repo.read("CN", DAY)["items"][0]["signals"]["industry"]["status"] == "unavailable"


def test_historical_rules_read_from_saved_generation(repo, monkeypatch):
    from finance_analysis.confluence import config

    seed(repo)
    service = ConfluenceService(repo)
    service.run("CN", DAY)
    monkeypatch.setattr(config, "STRONG_MIN_SCORE", 80)
    monkeypatch.setattr(config, "MIN_SIGNALS", 4)
    app = FastAPI()
    app.include_router(api.router, prefix="/confluence")
    app.dependency_overrides[api.get_service] = lambda: service
    app.dependency_overrides[api.require_current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        result = client.get("/confluence/ranking", params={"trade_date": DAY.isoformat()}).json()
        assert result["rules"]["strong_min_score"] == 75
        assert result["rules"]["min_signals"] == 3
        assert result["total"] == 1
    with repo.db.session_scope() as session:
        session.get(ConfluenceRun, ("CN", DAY)).rules = None
    assert service.ranking("CN", DAY)["rules"]["strong_min_score"] == 80
