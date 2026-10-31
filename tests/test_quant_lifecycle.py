"""Input leases, training admission, and transactional publication regressions.

PostgreSQL tests opt in through QUANT_TEST_DATABASE_URL and use a disposable schema.
"""
from contextlib import contextmanager
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4
import os

import pandas as pd
import pytest
from sqlalchemy import create_engine, select, text, func
from sqlalchemy.orm import Session

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.quant import (
    QUANT_TABLES, ModelDefinition, ModelRun, QuantExecution, QuantModelRelease,
    MarketRegimeSnapshot, PortfolioRecommendation,
)
from finance_analysis.database.models.user import User
from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.universe import Universe
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.quant.datasets.artifact_store import ArtifactStore
from finance_analysis.quant.datasets.transient import PredictionInputs, input_lock
from finance_analysis.quant.training import validate_training_dates
from finance_analysis.quant.targets import production_target_config


def test_prediction_input_lease_prevents_deletion(tmp_path):
    inputs = PredictionInputs(ArtifactStore(tmp_path))
    root = inputs.store.directory('temporary/example')
    (root / 'manifest.json').write_text('{}')
    with input_lock(root):
        assert not inputs.remove('quant://temporary/example')
        assert root.exists()
    assert inputs.remove('quant://temporary/example')
    assert not root.exists()
    assert inputs.remove('quant://temporary/example')
    assert not inputs.remove('quant://datasets/training')
    with pytest.raises(ValueError):
        inputs.remove('quant://temporary/../../escape')


def test_prediction_input_has_no_persistent_dataset_or_source_copy(tmp_path):
    dates = pd.bdate_range('2026-01-01', periods=80)
    rows = [dict(instrument=code, datetime=day.date(), open=10., high=12., low=9., close=11.,
                 volume=100., amount=1100., vwap=11.)
            for code in ['AAPL.US', 'SPY.US', 'QQQ.US', 'IWM.US'] for day in dates]
    inputs = PredictionInputs(ArtifactStore(tmp_path))
    uri = inputs.build('sample', 'US', 'us_quant', SimpleNamespace(frame=pd.DataFrame(rows).sort_values(["instrument", "datetime"]).reset_index(drop=True), source_revision='abc'),
                       {'AAPL.US'}, dates[0].date(), dates[-1].date())
    root = inputs.store.resolve_uri(uri)
    assert (root / 'manifest.json').exists()
    assert not (root / 'source/daily.csv').exists()
    assert list((root / 'features').glob('*/*.bin'))
    assert not list(root.glob('.export-*'))


@pytest.mark.parametrize('error', (RuntimeError, KeyboardInterrupt))
def test_failed_export_cleans_temporary_directory_and_partial_handoff(tmp_path, monkeypatch, error):
    from finance_analysis.quant.datasets.exporter import QlibDatasetExporter

    dates = pd.bdate_range('2026-01-01', periods=2)
    rows = [dict(instrument=code, datetime=day.date(), open=10., high=12., low=9., close=11.,
                 volume=100., amount=1100., vwap=11.)
            for code in ['AAPL.US', 'SPY.US', 'QQQ.US', 'IWM.US'] for day in dates]
    frame = pd.DataFrame(rows).sort_values(['instrument', 'datetime']).reset_index(drop=True)
    inputs = PredictionInputs(ArtifactStore(tmp_path))
    working_dirs = []

    def fail_export(_self, root, _frame, **_kwargs):
        working_dirs.append(root)
        (root / 'partial.bin').write_bytes(b'partial')
        raise error('export interrupted')

    monkeypatch.setattr(QlibDatasetExporter, '_write_qlib', fail_export)
    with pytest.raises(error, match='export interrupted'):
        inputs.build('failed', 'US', 'us_quant', SimpleNamespace(frame=frame, source_revision='test'),
                     {'AAPL.US'}, dates[0].date(), dates[-1].date())
    assert working_dirs and all(not path.exists() for path in working_dirs)
    assert not (tmp_path / 'temporary/failed').exists()


def test_training_admission_rejects_prediction_window_and_incomplete_fold():
    with pytest.raises(ValueError):
        validate_training_dates(pd.bdate_range('2020-01-01', periods=80))
    with pytest.raises(ValueError):
        validate_training_dates(pd.bdate_range('2020-01-01', periods=850))
    result = validate_training_dates(pd.bdate_range('2020-01-01', periods=1300))
    assert result['effective_from'] == '2020-03-25'
    assert result['sessions'] == 1300


@pytest.fixture
def pg_repo():
    url = os.environ.get('QUANT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('QUANT_TEST_DATABASE_URL is required for isolated PostgreSQL regression tests')
    engine = create_engine(url)
    schema = f'quant_test_{uuid4().hex}'
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    scoped = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    class Manager:
        @contextmanager
        def get_session(self):
            with Session(scoped) as session:
                yield session
        @contextmanager
        def session_scope(self):
            with Session(scoped) as session, session.begin():
                yield session
    try:
        tables = [User.__table__, Instrument.__table__, Universe.__table__, *(x.__table__ for x in QUANT_TABLES)]
        User.metadata.create_all(scoped, tables=tables)
        manager = Manager()
        with manager.session_scope() as session:
            session.add(User(id=1, username='quant-test', email='quant@example.test', role='admin'))
            session.add(Universe(id=1, key='us_quant', market='US', name='US Quant', enabled=True))
            session.add(Instrument(id=1, market='US', code='AAPL.US', name='Apple'))
            for i, key in enumerate(['cross_section_lgbm', 'time_series_lgbm'], 1):
                session.add(ModelDefinition(id=i, key=key, name=key, model_type=key.removesuffix('_lgbm'),
                                           task_type='regression', frequency='day'))
        yield QuantRepository(manager)
    finally:
        scoped.dispose()
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        engine.dispose()


def pair(repo, version):
    ids = repo.create_experiment('US', 1, 1, version, date(2020, 1, 1), date(2026, 1, 1))
    for key in ids:
        repo.update_model_run(key, status='candidate', artifact_uri=f'quant://models/{key}')
    return ids


def test_pair_publish_rollback_and_reference_protection(pg_repo):
    repo = pg_repo
    first = pair(repo, 'first')
    release = repo.publish_release('US', *first, 1, 'approved')
    second = pair(repo, 'second')
    with pytest.raises(ValueError):
        repo.publish_release('US', second[1], second[0], 1, 'wrong types')
    assert repo.active_release('US').id == release.id
    repo.publish_release('US', *second, 1, 'new pair')
    assert repo.get_model_run(first[0]).status == 'retired'
    with pytest.raises(ValueError, match='referenced'):
        repo.delete_model_run(first[0], 'US', 1)
    rollback = repo.publish_release('US', *first, 1, 'rollback')
    assert repo.active_release('US').id == rollback.id
    assert all(repo.get_model_run(key).status == 'production' for key in first)
    assert all(repo.get_model_run(key).status == 'retired' for key in second)
    assert not repo.update_model_run(first[0], expected_statuses={'training'}, status='candidate')


def test_daily_batch_is_atomic_idempotent_and_fenced(pg_repo):
    repo = pg_repo
    release = repo.publish_release('US', *pair(repo, 'first'), 1, 'approved')
    execution_id = str(uuid4())
    values = dict(id=execution_id, market='US', trade_date=date(2026, 1, 2), universe_id=1, release_id=release.id)
    repo.create_execution(values)
    with pytest.raises(ValueError, match='active'):
        repo.create_execution({**values, 'id': str(uuid4())})
    version = f'batch-{execution_id}'
    portfolio = dict(market='US', trade_date=values['trade_date'], universe_id=1, model_version=version,
                     status='ready', max_equity_exposure=.5, target_equity_exposure=0., summary={}, warnings=[])
    regime = dict(market='US', trade_date=values['trade_date'], model_version=version, regime='neutral',
                  market_score=.5, max_equity_exposure=.5)
    args = ('US', 1, values['trade_date'], version, [], portfolio)
    with pytest.raises(Exception):
        repo.replace_signals_and_save_portfolio(*args, [{'invalid_column': True}], regime_values=regime, execution_id=execution_id)
    with repo.db.get_session() as session:
        assert session.scalar(select(func.count()).select_from(MarketRegimeSnapshot)) == 0
    first = repo.replace_signals_and_save_portfolio(*args, [], regime_values=regime, execution_id=execution_id)
    second = repo.replace_signals_and_save_portfolio(*args, [], regime_values=regime, execution_id=execution_id)
    assert first.id == second.id
    with repo.db.get_session() as session:
        assert session.scalar(select(func.count()).select_from(PortfolioRecommendation)) == 1
    repo.update_execution(execution_id, status='failed')
    assert repo.execution(execution_id).status == 'complete'
    other = str(uuid4())
    repo.create_execution({**values, 'id': other})
    repo.update_execution(other, status='failed', finished_at=utc_now())
    with pytest.raises(ValueError, match='eligible'):
        repo.replace_signals_and_save_portfolio(*args, [], execution_id=other)


def test_cleanup_respects_heartbeat_and_reclaims_abandoned_inputs(pg_repo, tmp_path):
    from finance_analysis.quant.datasets.cleanup import cleanup_inputs
    repo = pg_repo
    manager = PredictionInputs(ArtifactStore(tmp_path))
    key = str(uuid4())
    root = manager.store.directory(f'temporary/{key}')
    heartbeat = root / '.lease'
    heartbeat.touch()
    repo.create_execution(dict(id=key, market='US', universe_id=1, trade_date=date(2026, 1, 2),
                               created_at=utc_now()-timedelta(days=3), input_uri=f'quant://temporary/{key}'))
    cleanup_inputs(repo, manager, dry_run=False)
    assert repo.execution(key).status == 'preparing'
    old = (utc_now()-timedelta(days=3)).timestamp()
    os.utime(heartbeat, (old, old))
    cleanup_inputs(repo, manager, dry_run=True)
    assert repo.execution(key).status == 'preparing'
    result = cleanup_inputs(repo, manager, dry_run=False)
    assert result['execution_ids'] == result['abandoned_execution_ids'] == [key]
    assert repo.execution(key).status == 'failed'
    assert repo.execution(key).input_uri is None
    assert not root.exists()


@pytest.mark.parametrize('status', ('complete', 'failed'))
def test_cleanup_reclaims_recent_terminal_inputs_without_retention(pg_repo, tmp_path, status):
    from finance_analysis.quant.datasets.cleanup import cleanup_inputs

    manager = PredictionInputs(ArtifactStore(tmp_path))
    key = str(uuid4())
    root = manager.store.directory(f'temporary/{key}')
    (root / '.lease').touch()
    pg_repo.create_execution(dict(id=key, market='US', universe_id=1, trade_date=date(2026, 1, 2),
                                 input_uri=f'quant://temporary/{key}'))
    pg_repo.update_execution(key, status=status, finished_at=utc_now())
    assert cleanup_inputs(pg_repo, manager, dry_run=False)['execution_ids'] == [key]
    assert not root.exists()
    assert pg_repo.execution(key).input_uri is None


def test_migration_bootstraps_production_pair_without_deleting_history(pg_repo):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    repo = pg_repo
    ids = pair(repo, 'legacy')
    for key in ids:
        repo.update_model_run(key, status='production')
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/0081_quant_lifecycle.py'
    spec = importlib.util.spec_from_file_location('quant_lifecycle_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with repo.db.session_scope() as session:
        connection = session.connection()
        QuantExecution.__table__.drop(connection)
        QuantModelRelease.__table__.drop(connection)
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert session.scalar(select(func.count()).select_from(ModelRun)) == 2
        release = session.scalar(select(QuantModelRelease))
        assert (release.cross_section_id, release.time_series_id, release.active) == (*ids, True)
        module.downgrade()
        assert session.scalar(select(func.count()).select_from(ModelRun)) == 2


def test_duplicate_training_dispatch_does_not_fail_running_model(monkeypatch):
    from unittest.mock import MagicMock
    from finance_analysis.quant.pipeline.service import QuantTrainingPipeline
    from finance_analysis.quant.exceptions import TrainingAlreadyStartedError
    repo = MagicMock()
    repo.get_model_run.return_value = SimpleNamespace(id=1, status='training', market='US', universe_id=1)
    repo.get_universe.return_value = SimpleNamespace(key='us_quant', market='US', enabled=True)
    with pytest.raises(TrainingAlreadyStartedError):
        QuantTrainingPipeline(repo).prepare(1)
    repo.update_model_run.assert_not_called()


def test_training_callback_replay_preserves_published_status():
    from unittest.mock import MagicMock
    from finance_analysis.quant.pipeline.service import QuantTrainingPipeline
    repo = MagicMock()
    repo.get_model_run.return_value = SimpleNamespace(id=1, status='production', market='US', universe_id=1,
        model_key='cross_section_lgbm', artifact_uri='quant://models/1')
    repo.get_universe.return_value = SimpleNamespace(key='us_quant', market='US', enabled=True)
    result = QuantTrainingPipeline(repo).finalize(1, dict(schema_version=1, model_run_id=1,
        model_key='cross_section_lgbm', artifact_uri='quant://models/1'))
    assert result['status'] == 'production'
    repo.update_model_run.assert_not_called()
