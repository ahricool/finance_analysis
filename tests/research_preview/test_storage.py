"""Latest publication semantics, normalized storage, and bounded API reads."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import event, func, select

from finance_analysis.core.preview_storage import factor_common, merge_dict
from finance_analysis.core.preview_views import encode
from finance_analysis.database.models.research_preview import ResearchPreview, ResearchPreviewItem
from finance_analysis.database.models.stock import Instrument
from finance_analysis.trend_following import preview_cache as trend
from finance_analysis.trend_following.table import preview_views
from tests.preview_database import preview_repository
from tests.test_research_read_views import payload


@pytest.fixture
def store():
    return preview_repository()


def test_full_roundtrip_factoring_and_all_views_are_lossless(store):
    data = payload()
    second = deepcopy(data['snapshots'][0])
    second.update(code='000001.SZ', name='平安银行', rank=2)
    second['features']['return_20d'] = 0.123456789
    second['score_breakdown']['alpha']['contributions']['trend'] = 12.3456789
    data['snapshots'].append(second)
    data['snapshot_count'] = 2
    original = deepcopy(data)
    trend.save_preview('CN', data, repository=store)
    assert data == original
    assert trend.load_preview('CN', repository=store) == data
    for key, expected in preview_views(data).items():
        assert json.loads(trend.load_preview_view('CN', key, repository=store)) == expected
    with store.db.get_session() as session:
        batch = session.get(ResearchPreview, ('trend_following', 'CN', 20))
        assert 'snapshots' not in batch.header
        assert batch.shared['values']['features']['unused'] == [1] * 1000
        rows = session.scalars(select(ResearchPreviewItem)).all()
        assert len(rows) == 2
        assert all('unused' not in row.detail.get('features', {}) for row in rows)
        assert all('name' not in batch.shared for _ in rows)
        # No materialized full document, ranking table or stock HTTP response copies.
        assert all('table' not in row.summary and 'latest' not in row.detail for row in rows)


def test_names_are_joined_from_instrument_without_losing_unknown_names(store):
    with store.db.session_scope() as session:
        session.add(Instrument(id=1, market='CN', code='600519.SH', name='主数据名称'))
    data = payload()
    trend.save_preview('CN', data, repository=store)
    with store.db.get_session() as session:
        row = session.scalars(select(ResearchPreviewItem)).one()
        assert row.instrument_id == 1
        assert 'name' not in row.summary and 'name' not in row.detail
    assert trend.load_preview('CN', repository=store)['snapshots'][0]['name'] == '主数据名称'
    with store.db.session_scope() as session:
        session.get(Instrument, 1).name = '更新名称'
    assert trend.load_preview('CN', repository=store)['snapshots'][0]['name'] == '更新名称'


def test_replacement_scope_rollback_and_older_publication(store):
    data = payload()
    for market in ('CN', 'US'):
        for period in (20, 40, 60):
            trend.save_preview(market, {**data, 'trend_period': period}, repository=store)
    original = trend.load_preview('CN', repository=store)

    def fail(_connection, _cursor, statement, _params, _context, _many):
        if statement.startswith('INSERT INTO research_preview_item'):
            raise RuntimeError('disk full')

    event.listen(store.db.engine, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='Failed to save'):
            trend.save_preview('CN', {**data, 'preview_time': '2026-10-14T07:00:00Z'}, repository=store)
    finally:
        event.remove(store.db.engine, 'before_cursor_execute', fail)
    assert trend.load_preview('CN', repository=store) == original
    failed = {**data, 'preview_time': '2026-10-14T07:00:00Z', 'status': 'failed', 'snapshots': []}
    trend.save_preview('CN', failed, repository=store)
    trend.save_preview('CN', data, repository=store)  # Late older worker must not restore obsolete results.
    assert trend.load_preview('CN', repository=store)['snapshots'] == []
    assert trend.load_preview('US', repository=store)['snapshots']
    assert trend.load_preview('CN', trend_period=40, repository=store)['snapshots']
    with store.db.get_session() as session:
        assert session.scalar(select(func.count()).select_from(ResearchPreview)) == 6
        assert session.scalar(select(func.count()).select_from(ResearchPreviewItem)) == 5


def test_expiry_and_bounded_queries(store):
    trend.save_preview('CN', payload(), repository=store)
    statements = []
    def record(_conn, _cursor, sql, _params, _context, _many):
        statements.append(sql)
    event.listen(store.db.engine, 'before_cursor_execute', record)
    try:
        trend.load_preview_view('CN', 'status', repository=store)
        assert len(statements) == 1 and 'research_preview_item' not in statements[0]
        statements.clear()
        trend.load_preview_view('CN', 'stock:600519.SH', repository=store)
        assert len(statements) == 2 and 'research_preview_item.item_key = ?' in statements[1]
        statements.clear()
        trend.load_preview_view('CN', 'ranking', repository=store)
        assert len(statements) == 2
        assert ', research_preview_item.detail,' not in statements[1]
    finally:
        event.remove(store.db.engine, 'before_cursor_execute', record)
    with store.db.session_scope() as session:
        session.get(ResearchPreview, ('trend_following', 'CN', 20)).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert trend.load_preview('CN', repository=store) is None


def test_factoring_preserves_missing_null_false_zero_and_originals():
    rows = [{'code': 'A', 'x': None, 'y': {'flag': False, 'n': 0, 'v': 1.234567890123}},
            {'code': 'B', 'x': None, 'y': {'flag': False, 'n': 0, 'v': 1.234567890124}},
            {'code': 'C', 'x': None, 'y': {'flag': False, 'n': 0}}]
    original = deepcopy(rows)
    shared, residuals = factor_common(rows)
    assert rows == original
    assert [merge_dict(shared, r) for r in residuals] == rows
    assert 'v' not in shared['y']
    assert len(encode(shared)) + len(encode(residuals)) < len(encode(rows))


def test_factoring_does_not_coerce_nested_json_types():
    rows = [{"code": "A", "x": {"items": [False, 1]}}, {"code": "B", "x": {"items": [0, 1.0]}}]
    common, residuals = factor_common(rows)
    restored = [merge_dict(common, row) for row in residuals]
    assert encode(restored) == encode(rows)


def test_aliases_and_score_components_are_stored_once_and_restored(store):
    data = payload()
    row = data['snapshots'][0]
    row.update(reference_price=100.123456789, entry_score=0, entry_type='NONE', atr=1.25, trend_period=20)
    row['features'].update(reference_price=row['reference_price'], entry_score=0, entry_type='NONE', atr20=1.25, trend_period=20)
    second = deepcopy(row)
    second.update(code='000001.SZ', rank=2, reference_price=20.0)
    second['features']['reference_price'] = 20.0
    second['features']['return_20d'] = 0.5
    data['snapshots'].append(second)
    data['snapshot_count'] = 2
    trend.save_preview('CN', data, repository=store)
    assert trend.load_preview('CN', repository=store) == data
    with store.db.get_session() as session:
        saved = session.scalars(select(ResearchPreviewItem)).first()
        assert 'reference_price' not in saved.summary.get('features', {})
        assert 'entry_score' not in saved.summary.get('features', {})
        assert 'trend' not in saved.detail.get('score_breakdown', {}).get('alpha', {}).get('contributions', {})
    assert json.loads(trend.load_preview_view('CN', 'ranking', repository=store)) == preview_views(data)['ranking']


@pytest.mark.parametrize('events', [[], [{'event_type': 'A', 'severity': 2}, {'event_type': 'B', 'severity': 5}]])
@pytest.mark.parametrize('extra', [{}, {'event_types': ['original'], 'top_event': {'original': True}}])
def test_options_summary_event_factoring_is_lossless(store, events, extra):
    from finance_analysis.options_intelligence.preview_cache import load_preview, save_preview
    stamp = datetime(2026, 10, 28, 18, tzinfo=timezone.utc)
    row = {'symbol': 'AAPL.US', 'events': events, 'contracts': [{'price': 1.23456789}], **extra}
    save_preview({'trade_date': '2026-10-28', 'items': [row]}, repository=store, now=stamp)
    assert load_preview(repository=store, now=stamp, symbol='AAPL.US') == row


def test_latest_scope_uses_run_start_even_if_older_run_finishes_last(store):
    first = {**payload(), 'run_started_at': '2026-10-14T05:00:00Z', 'preview_time': '2026-10-14T06:00:00Z'}
    second = {**payload(), 'run_started_at': '2026-10-14T05:30:00Z', 'preview_time': '2026-10-14T05:40:00Z'}
    trend.save_preview('CN', second, repository=store)
    trend.save_preview('CN', first, repository=store)
    assert trend.load_preview('CN', repository=store)['run_started_at'] == second['run_started_at']
