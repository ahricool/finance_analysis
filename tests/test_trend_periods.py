"""Periodized calculations and storage isolation; no database or network services."""
import importlib.util
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot
from finance_analysis.database.repositories.trend_following import TrendFollowingRepository
from finance_analysis.trend_following.config import DEFAULT_CONFIG
from finance_analysis.trend_following.duration import count_trend_duration_days
from finance_analysis.trend_following.features import calculate_features, true_ranges
from finance_analysis.trend_following.mean_reversion import calculate_mean_reversion
from finance_analysis.trend_following.models import DailyBar
from finance_analysis.trend_following.ranking import rank_candidates
from tests.test_trend_following_repository import _Database, _snapshot, _summary


def bars(count=130):
    closes = [100 * np.exp(.002 * i + .025 * np.sin(i / 6)) for i in range(count)]
    return [DailyBar(date(2026, 1, 1) + timedelta(days=i), c, c + 2, c - 1, c, 1000 + i * 7)
            for i, c in enumerate(closes)]


@pytest.mark.parametrize('period', [20, 40, 60])
def test_every_price_window_and_rsi_follow_period(period):
    config = replace(DEFAULT_CONFIG, trend_period=period)
    history = bars()
    row = calculate_features(history, config=config)
    closes = np.array([b.close for b in history])
    assert row['trend_period'] == period
    assert row['ma10'] == pytest.approx(closes[-period // 2:].mean())
    assert row['ma20'] == pytest.approx(closes[-period:].mean())
    assert row['atr20'] == pytest.approx(true_ranges(history)[-period:].mean())
    for key, window in [('3d', period * 3 // 20), ('5d', period // 4), ('10d', period // 2), ('20d', period)]:
        assert row[f'return_{key}'] == pytest.approx(closes[-1] / closes[-window - 1] - 1)
    expected = np.polyfit(np.arange(period), np.log(closes[-period:]), 1, w=np.sqrt(np.arange(1, period + 1)))
    assert row['raw_weighted_slope'] == pytest.approx(expected[0])
    assert row['previous_high_20'] == max(b.high for b in history[-period - 1:-1])
    assert row['previous_high_10'] == max(b.high for b in history[-period // 2 - 1:-1])
    assert row['volume_ratio'] == pytest.approx(history[-1].volume / np.mean([b.volume for b in history[-period - 1:-1]]))
    # At the first RSI observation Wilder's seed is exactly N daily changes.
    initial = history[:period + 1]
    changes = np.diff([b.close for b in initial])
    gains, losses = np.maximum(changes, 0).mean(), np.maximum(-changes, 0).mean()
    expected_rsi = 100 if losses == 0 else 100 - 100 / (1 + gains / losses)
    mr = calculate_mean_reversion(initial, calculate_features(initial, config=config), config)
    assert mr['rsi14'] == pytest.approx(expected_rsi)
    assert config.box_windows == (period,)
    assert calculate_features(history[-period:], config=config) is None
    assert calculate_features(history[-period - 1:], config=config) is not None


@pytest.mark.parametrize('period', [20, 40, 60])
def test_duration_uses_selected_period_and_excludes_future(period):
    history = [replace(bar, close=100 + i, high=102 + i, low=99 + i) for i, bar in enumerate(bars(100))]
    config = replace(DEFAULT_CONFIG, trend_period=period)
    assert count_trend_duration_days(history, as_of=history[-1].trade_date, config=config) == 100 - period
    assert count_trend_duration_days(history, as_of=history[80].trade_date, config=config) == 81 - period


def test_period_changes_complete_alpha_scoring_not_only_regression():
    scores = []
    for period in (20, 40, 60):
        config = replace(DEFAULT_CONFIG, trend_period=period)
        rows = []
        for code, history in [('A.US', bars()), ('B.US', [replace(b, close=100 + i) for i, b in enumerate(bars())])]:
            row = calculate_features(history, config=config)
            row.update(code=code, rs_5d=row['return_5d'], rs_10d=row['return_10d'], rs_20d=row['return_20d'])
            rows.append(row)
        scored = rank_candidates(rows, config)
        scores.append(next(r['alpha_score'] for r in scored if r['code'] == 'A.US'))
    assert len(set(scores)) == 3


def test_snapshots_history_replacement_and_invalidation_never_cross_periods(monkeypatch):
    monkeypatch.setattr('finance_analysis.trend_following.ranking_cache.invalidate_market', lambda _: None)
    database = _Database()
    day = date(2026, 8, 28)
    with database.session_scope() as session:
        session.add(Instrument(id=1, market='US', code='AAA.US', name='AAA'))
    repositories = {p: TrendFollowingRepository('US', database, trend_period=p) for p in (20, 40, 60)}
    for period, repo in repositories.items():
        row = _snapshot(snapshot_id=1, code='AAA.US', instrument_id=1, trade_date=day)
        payload = {col.name: getattr(row, col.name) for col in TrendFollowingSnapshot.__table__.columns}
        payload['alpha_score'] = period
        repo.replace_day(day, [payload], _summary(day))
    for period, repo in repositories.items():
        assert repo.snapshot_history('AAA.US', limit=10)[0]['alpha_score'] == period
        assert repo.summary_by_date(day)['trend_period'] == period
        assert repo.previous_snapshots(day + timedelta(days=1), ['AAA.US'])['AAA.US']['trend_period'] == period
        assert len(repo.dashboard_rows(day)) == 1
    repositories[40].replace_day(day, [], _summary(day))
    repositories[60].invalidate_from(day)
    assert len(repositories[20].snapshots_by_date(day)) == 1
    assert repositories[40].snapshots_by_date(day) == []
    assert repositories[60].summary_by_date(day) is None
    assert repositories[20].historical_composite_ranks(day + timedelta(days=1), ['AAA.US']) == {'AAA.US': {1: 1}}


@pytest.mark.parametrize('instrument_indexes', ['legacy', 'current', 'both', 'missing'])
def test_migration_clears_old_results_and_keys_new_results_by_period(instrument_indexes):
    path = Path(__file__).parents[1] / 'alembic/versions/0072_trend_periods.py'
    spec = importlib.util.spec_from_file_location('trend_period_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        for table, (unique, columns, indexes) in migration.TABLES.items():
            fields = {'market': 'TEXT', 'trade_date': 'DATE', 'code': 'TEXT', 'instrument_id': 'INTEGER',
                      'alpha_score': 'FLOAT', 'state': 'TEXT'}
            connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, " + ', '.join(f'{k} {v}' for k, v in fields.items())
                                    + f", CONSTRAINT {unique} UNIQUE ({', '.join(columns)}))"))
            # Historical 0031 + 0039 retains the symbol index name even though
            # its column is now instrument_id; do not derive that fixture from 0072.
            existing_indexes = {
                'ix_trend_following_market_date_alpha': ['market', 'trade_date', 'alpha_score'],
                'ix_trend_following_market_date_state': ['market', 'trade_date', 'state'],
            } if table == 'trend_following_snapshot' else {
                'ix_trend_following_summary_market_date': ['market', 'trade_date'],
            }
            if table == 'trend_following_snapshot':
                if instrument_indexes in ('legacy', 'both'):
                    existing_indexes['ix_trend_following_symbol_date'] = ['instrument_id', 'trade_date']
                if instrument_indexes in ('current', 'both'):
                    existing_indexes['ix_trend_following_instrument_date'] = ['instrument_id', 'trade_date']
            for index, names in existing_indexes.items():
                connection.execute(text(f"CREATE INDEX {index} ON {table} ({', '.join(names)})"))
            connection.execute(text(f"INSERT INTO {table} (id, market, trade_date, code) VALUES (1, 'US', '2026-08-28', 'AAA.US')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        for table in migration.TABLES:
            assert connection.scalar(text(f'SELECT count(*) FROM {table}')) == 0
            assert any(c['name'] == 'trend_period' and not c['nullable'] for c in inspect(connection).get_columns(table))
            for period in (20, 40, 60):
                connection.execute(text(f"INSERT INTO {table} (market, trade_date, code, trend_period) VALUES ('US', '2026-08-28', 'AAA.US', :period)"), {'period': period})
            assert connection.scalar(text(f'SELECT count(*) FROM {table}')) == 3
            actual_indexes = {i['name']: i['column_names'] for i in inspect(connection).get_indexes(table)}
            assert actual_indexes == {
                name: [fields[0], 'trend_period', *fields[1:]]
                for name, fields in migration.TABLES[table][2].items()
            }
        migration.downgrade()
        assert 'trend_period' not in {c['name'] for c in inspect(connection).get_columns('trend_following_snapshot')}
        for table, (_, _, indexes) in migration.TABLES.items():
            assert {i['name']: i['column_names'] for i in inspect(connection).get_indexes(table)} == indexes
        migration.upgrade()


def test_api_validates_period_and_scopes_repository(monkeypatch):
    from finance_analysis.interfaces.api.v1.endpoints import trend_following as api
    from finance_analysis.interfaces.api.deps import require_current_user
    seen = []
    def repository(market, *, trend_period):
        seen.append((market, trend_period))
        return SimpleNamespace(available_trade_dates=lambda: [])
    monkeypatch.setattr(api, 'TrendFollowingRepository', repository)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        assert client.get('/dates?market=US&trend_period=40').status_code == 200
        assert client.get('/dates?trend_period=15').status_code == 422
        assert client.get('/dates?trend_period=30').status_code == 422
        assert client.get('/dates').status_code == 200
    assert seen == [('US', 40), ('CN', 20)]


def test_task_runs_three_independent_periods_with_shared_inputs(monkeypatch):
    from finance_analysis.tasks.celery.jobs.trend_following import tasks
    calls = []
    def service(market, *, config, input_cache):
        calls.append((config.trend_period, input_cache))
        return SimpleNamespace(run=lambda day: {'status': 'completed', 'trend_period': config.trend_period})
    monkeypatch.setattr(tasks, 'TrendFollowingService', service)
    result = tasks._run('CN', None)
    assert list(result['periods']) == ['20', '40', '60']
    assert [p for p, _ in calls] == [20, 40, 60]
    assert all(cache is calls[0][1] for _, cache in calls)


def test_preview_and_read_caches_are_isolated_by_period():
    from finance_analysis.trend_following.event_study_cache import EventStudyCache
    from finance_analysis.trend_following.preview_cache import load_preview, save_preview
    from finance_analysis.trend_following.ranking_cache import RankingCache

    from tests.preview_redis import MemoryRedis

    client = MemoryRedis()
    day = date(2026, 10, 12)
    for period in (20, 40, 60):
        save_preview('US', {'trend_period': period, 'snapshots': [{'alpha_score': period}]}, client=client)
    for period in (20, 40, 60):
        payload = load_preview('US', trend_period=period, client=client)
        assert payload['trend_period'] == period
        assert payload['snapshots'][0]['alpha_score'] == period
    assert len({RankingCache('US', day, period).key for period in (20, 40, 60)}) == 3
    assert len({EventStudyCache('US', day, day, 'ALL', period).key for period in (20, 40, 60)}) == 3
