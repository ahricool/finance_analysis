from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from finance_analysis.database.models.quant import (
    ModelDefinition,
    ModelPrediction,
    ModelPublication,
    ModelRun,
    QuantDatasetSnapshot,
    QuantUniverse,
)
from finance_analysis.database.models.stock import MarketDataSymbol
from finance_analysis.database.models.user import User
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.quant.datasets.artifact_store import ArtifactStore


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class SqliteManager:
    def __init__(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        event.listen(self.engine, "connect", lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"))

    @contextmanager
    def get_session(self):
        with Session(self.engine) as session:
            yield session

    @contextmanager
    def session_scope(self):
        with Session(self.engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise


def _database() -> SqliteManager:
    database = SqliteManager()
    for table in (
        User.__table__,
        MarketDataSymbol.__table__,
        QuantUniverse.__table__,
        QuantDatasetSnapshot.__table__,
        ModelDefinition.__table__,
        ModelRun.__table__,
        ModelPublication.__table__,
        ModelPrediction.__table__,
    ):
        table.create(database.engine)
    with Session(database.engine) as session:
        session.add_all(
            [
                User(id=1, username="admin", email="admin@example.com", role="admin"),
                MarketDataSymbol(id=1, market="US", code="AAPL.US", name="Apple"),
                QuantUniverse(id=1, key="us_sp500", name="S&P 500", market="US", enabled=True),
                ModelDefinition(
                    id=1,
                    key="cross_section_lgbm",
                    name="Cross section",
                    model_type="cross_section",
                    task_type="regression",
                    frequency="day",
                    supported_markets=["US"],
                ),
            ]
        )
        session.commit()
    return database


def _dataset(identifier: int, status: str = "ready") -> QuantDatasetSnapshot:
    return QuantDatasetSnapshot(
        id=identifier,
        dataset_key=f"dataset-{identifier}",
        market="US",
        universe_id=1,
        frequency="day",
        date_from=date(2025, 1, 1),
        date_to=date(2025, 12, 31),
        price_mode="forward_adjusted",
        feature_version="v1",
        source_revision=f"revision-{identifier}",
        artifact_uri=f"quant://datasets/{identifier}",
        status=status,
    )


def _model_run(identifier: int, dataset_id: int, status: str) -> ModelRun:
    return ModelRun(
        id=identifier,
        uid=1,
        model_definition_id=1,
        model_key="cross_section_lgbm",
        model_version=f"model-{identifier}",
        run_type="train",
        market="US",
        universe_id=1,
        dataset_snapshot_id=dataset_id,
        status=status,
        progress=100,
        artifact_uri=f"quant://models/{identifier}",
    )


def test_dataset_deletion_rejects_active_and_referenced_snapshots() -> None:
    database = _database()
    with Session(database.engine) as session:
        session.add_all([_dataset(1, "building"), _dataset(2)])
        session.flush()
        session.add(_model_run(10, 2, "candidate"))
        session.commit()
    repository = QuantRepository(database)

    with pytest.raises(ValueError, match="pending or building"):
        repository.delete_dataset(1, "US", 1)
    with pytest.raises(ValueError, match="model run 10"):
        repository.delete_dataset(2, "US", 1)

    with Session(database.engine) as session:
        assert session.get(QuantDatasetSnapshot, 1) is not None
        assert session.get(QuantDatasetSnapshot, 2) is not None


def test_model_run_deletion_removes_publication_predictions_and_then_allows_dataset_delete() -> None:
    database = _database()
    with Session(database.engine) as session:
        session.add(_dataset(2))
        session.flush()
        session.add(_model_run(10, 2, "retired"))
        session.flush()
        session.add_all(
            [
                ModelPublication(id=1, model_run_id=10, published_by=1, reason="superseded"),
                ModelPrediction(
                    id=1,
                    model_run_id=10,
                    trade_date=date(2026, 1, 2),
                    symbol_id=1,
                    code="AAPL.US",
                    raw_prediction=0.1,
                    normalized_score=0.2,
                ),
            ]
        )
        session.commit()
    repository = QuantRepository(database)

    deleted_run = repository.delete_model_run(10, "US", 1)
    deleted_dataset = repository.delete_dataset(2, "US", 1)

    assert deleted_run == {"id": 10, "artifact_uri": "quant://models/10"}
    assert deleted_dataset == {"id": 2, "artifact_uri": "quant://datasets/2"}
    with Session(database.engine) as session:
        assert session.get(ModelRun, 10) is None
        assert session.execute(select(ModelPublication)).scalar_one_or_none() is None
        assert session.execute(select(ModelPrediction)).scalar_one_or_none() is None
        assert session.get(QuantDatasetSnapshot, 2) is None


@pytest.mark.parametrize("status", ["draft", "training", "production"])
def test_model_run_deletion_rejects_runtime_dependencies(status: str) -> None:
    database = _database()
    with Session(database.engine) as session:
        session.add(_dataset(2))
        session.flush()
        session.add(_model_run(10, 2, status))
        session.commit()

    with pytest.raises(ValueError, match=status):
        QuantRepository(database).delete_model_run(10, "US", 1)

    with Session(database.engine) as session:
        assert session.get(ModelRun, 10) is not None


def test_artifact_store_deletes_only_the_requested_artifact(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    target = store.directory("models/model-1")
    (target / "model.pkl").write_bytes(b"model")
    sibling = store.directory("models/model-2")
    (sibling / "model.pkl").write_bytes(b"keep")

    assert store.delete_uri("quant://models/model-1") is True
    assert not target.exists()
    assert (sibling / "model.pkl").read_bytes() == b"keep"
    assert store.delete_uri("quant://models/model-1") is False


def test_artifact_store_unlinks_a_symlink_without_deleting_its_target(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    store = ArtifactStore(root)
    link = root / "models" / "linked-model"
    link.parent.mkdir()
    link.symlink_to(outside, target_is_directory=True)

    assert store.delete_uri("quant://models/linked-model") is True
    assert not link.exists()
    assert (outside / "keep.txt").read_text() == "keep"


@pytest.mark.parametrize("uri", ["quant://", "quant://.", "quant://../outside", "file:///tmp/model"])
def test_artifact_store_rejects_root_traversal_and_unsupported_uris(tmp_path: Path, uri: str) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(ValueError):
        store.delete_uri(uri)

    assert tmp_path.exists()
