from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, update
from sqlalchemy.pool import StaticPool

from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot, TrendFollowingSummary
from finance_analysis.database.repositories import trend_following as repositories
from finance_analysis.interfaces.api.v1.endpoints import trend_following as endpoints
from finance_analysis.trend_following import breadth
from tests.test_trend_following_repository import _Database, _snapshot, _summary

TODAY = date(2026, 9, 14)
STATES = ['IDLE', 'WATCHING', 'CANDIDATE', 'TRENDING', 'WEAKENING', 'BROKEN']


@pytest.fixture
def source(monkeypatch):
    database = _Database()
    database.engine.dispose()
    database.engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    for model in (Instrument, TrendFollowingSnapshot, TrendFollowingSummary):
        model.__table__.create(database.engine)
    # Deliberately irregular sessions; the query must never infer a weekday calendar.
    dates = [TODAY - timedelta(days=70 - i * 2) for i in range(35)]
    with database.session_scope() as session:
        session.add_all([Instrument(id=i + 1, market='US', code=f'S{i}.US', name=f'Stock {i}') for i in range(8)])
        session.add(Instrument(id=100, market='CN', code='600000.SH', name='CN'))
        for index, day in enumerate(dates):
            for i, state in enumerate([*STATES, 'TRENDING', 'WATCHING']):
                row = _snapshot(snapshot_id=index * 8 + i + 1, code=f'S{i}.US', instrument_id=i + 1,
                                trade_date=day, state=state)
                row.rank = i + 1 if i < 6 else 0
                session.add(row)
            session.add(TrendFollowingSummary(id=index + 1, **{**_summary(day), 'rankable_count': 6}))
        row = _snapshot(snapshot_id=5000, code='600000.SH', instrument_id=100, trade_date=TODAY)
        row.market = 'CN'
        session.add(row)
        session.add(TrendFollowingSummary(id=5000, **{**_summary(TODAY), 'market': 'CN', 'rankable_count': 1}))
    original = repositories.TrendFollowingRepository
    monkeypatch.setattr(repositories, 'TrendFollowingRepository', lambda market: original(market, database))
    monkeypatch.setattr(breadth, 'get_market_now', lambda market: datetime.combine(TODAY, datetime.min.time(), timezone.utc))
    preview = Mock(return_value=None)
    monkeypatch.setattr(breadth, 'load_preview', preview)
    statements = []
    event.listen(database.engine, 'before_cursor_execute', lambda *args: statements.append(args[2]))
    return database, dates, preview, statements


def test_thirty_actual_sessions_groups_denominator_and_three_queries(source):
    _, dates, preview, sql = source
    result = breadth.get_breadth_history('US')
    assert result['dates'] == dates[-30:]
    assert (result['dates'][-1] - result['dates'][0]).days > 30
    assert result['official_count'] == 30
    point = result['points'][-1]
    assert point['rankable_count'] == 6  # Eight snapshots; two unrankable rows excluded.
    assert point['coverage'] == 1 and point['warning'] is None
    assert point['trend_breadth'] == pytest.approx(1 / 6)
    assert point['participation'] == pytest.approx(2 / 6)
    assert point['deterioration_breadth'] == pytest.approx(2 / 6)
    assert [point[key] for key in breadth.STATE_GROUPS] == pytest.approx([2 / 6, 1 / 6, 1 / 6, 2 / 6])
    assert sum(point[key] for key in breadth.STATE_GROUPS) == pytest.approx(1)
    assert all(value == 1 for value in point['state_counts'].values())
    assert len(sql) == 3
    assert 'GROUP BY' in sql[1] and 'features' not in ''.join(sql)
    preview.assert_not_called()


def make_preview():
    return {'market': 'US', 'status': 'completed', 'trade_date': TODAY.isoformat(), 'rankable_count': 6,
            'snapshots': [{'code': f'S{i}.US', 'state': 'TRENDING' if i == 2 else state, 'rank': 6 - i}
                          for i, state in enumerate(STATES)]}


def test_preview_is_extra_31st_point_with_no_db_writes(source):
    _, dates, preview, sql = source
    preview.return_value = make_preview()
    result = breadth.get_breadth_history('US', include_preview=True)
    assert result['dates'] == [*dates[-30:], TODAY]
    assert result['official_count'] == 30
    assert result['points'][-1]['is_preview'] is True
    assert result['points'][-1]['trend_breadth'] == pytest.approx(2 / 6)
    assert result['points'][-1]['coverage'] == 1
    assert len(sql) == 3 and all(statement.startswith('SELECT') for statement in sql)


@pytest.mark.parametrize('api', [breadth.get_breadth_history, breadth.get_transitions])
def test_same_day_official_wins_and_market_isolation(source, api):
    _, _, preview, _ = source
    preview.return_value = {**make_preview(), 'market': 'CN'}
    result = api('CN', include_preview=True)
    assert result['preview_date'] is None
    if 'points' in result:
        assert result['dates'] == [TODAY]
        assert result['points'][0]['trend_breadth'] == 1
    else:
        assert result['items'] == []
    preview.assert_not_called()


@pytest.mark.parametrize('patch', [
    {'status': 'failed'}, {'status': 'incomplete'}, {'trade_date': '2026-09-11'},
    {'trade_date': '2026-09-15'}, {'market': 'CN'}, {'snapshots': []},
])
def test_invalid_preview_not_used(source, patch):
    _, _, preview, _ = source
    preview.return_value = {**make_preview(), **patch}
    for api in [breadth.get_breadth_history, breadth.get_transitions]:
        result = api('US', include_preview=True)
        assert result['preview_date'] is None and result['warnings']


def test_coverage_loss_and_missing_summary_not_normalized(source):
    database, dates, _, _ = source
    with database.session_scope() as session:
        session.execute(delete(TrendFollowingSnapshot).where(TrendFollowingSnapshot.code == 'S1.US'))
        session.execute(update(TrendFollowingSnapshot).where(TrendFollowingSnapshot.code == 'S0.US').values(rank=0))
        session.execute(delete(TrendFollowingSummary).where(TrendFollowingSummary.trade_date == dates[-2]))
    result = breadth.get_breadth_history('US')
    point = result['points'][-1]
    assert point['coverage'] == pytest.approx(4 / 6) and point['warning']
    assert sum(point[key] for key in breadth.STATE_GROUPS) == pytest.approx(4 / 6)
    missing = result['points'][-2]
    assert missing['trend_breadth'] is None and missing['coverage'] is None and missing['warning']
    # Legacy null state never fails aggregation, although current schema prohibits null.
    point = breadth.aggregate_point(TODAY, {None: 1, 'TRENDING': 1}, 2)
    assert point['coverage'] == 0.5 and point['warning']
    assert breadth.aggregate_point(TODAY, {}, 0)['trend_breadth'] is None


def test_historical_cutoff_no_future_or_preview(source):
    _, dates, preview, _ = source
    for api in [breadth.get_breadth_history, breadth.get_transitions]:
        result = api('US', as_of=dates[-2], include_preview=True)
        assert result['preview_date'] is None
        if 'dates' in result:
            assert result['dates'][-1] == dates[-2]
        assert api('US', as_of=dates[0] - timedelta(days=1)).get('points', []) == []
        with pytest.raises(ValueError):
            api('US', as_of=TODAY + timedelta(days=1))
    preview.assert_not_called()


def seed_transitions(source):
    database, dates, _, sql = source
    # Six adjacent persisted sessions produce five transitions, including a recovery and a breakdown.
    sequence = ['WATCHING', 'CANDIDATE', 'TRENDING', 'WEAKENING', 'TRENDING', 'BROKEN']
    with database.session_scope() as session:
        for index, (day, state) in enumerate(zip(dates[-6:], sequence)):
            session.execute(update(TrendFollowingSnapshot).where(
                TrendFollowingSnapshot.code == 'S0.US', TrendFollowingSnapshot.trade_date == day,
            ).values(state=state, rank=10 - index))
    sql.clear()


@pytest.mark.parametrize('days', [1, 3, 5])
def test_adjacent_transitions_ranges_rank_delta_and_two_queries(source, days):
    seed_transitions(source)
    _, dates, _, sql = source
    result = breadth.get_transitions('US', days=days)
    assert len(result['items']) == days
    assert [row['trade_date'] for row in result['items']] == dates[-days:][::-1]
    assert result['items'][0]['previous_date'] == dates[-2]
    assert result['items'][0]['rank_delta'] == 1
    assert result['official_count'] == days
    assert result['items'][0]['current_rank'] == 5 and result['items'][0]['previous_rank'] == 6
    assert len(sql) == 2
    assert 'features' not in ''.join(sql)


@pytest.mark.parametrize('pair,classification', list(breadth.TRANSITIONS.items()))
def test_explicit_transition_classification(source, pair, classification):
    database, dates, _, _ = source
    with database.session_scope() as session:
        for day, state in zip(dates[-2:], pair):
            session.execute(update(TrendFollowingSnapshot).where(
                TrendFollowingSnapshot.code == 'S0.US', TrendFollowingSnapshot.trade_date == day,
            ).values(state=state))
    rows = breadth.get_transitions('US', days=1, direction=classification[0])['items']
    assert len(rows) == 1 and rows[0]['priority'] == classification[1]
    other = 'strengthening' if classification[0] == 'deteriorating' else 'deteriorating'
    assert breadth.get_transitions('US', days=1, direction=other)['items'] == []


@pytest.mark.parametrize('pair', [('IDLE', 'WATCHING'), ('BROKEN', 'WATCHING'), ('WATCHING', 'IDLE')])
def test_neutral_transitions_excluded(source, pair):
    database, dates, _, _ = source
    with database.session_scope() as session:
        for day, state in zip(dates[-2:], pair):
            session.execute(update(TrendFollowingSnapshot).where(
                TrendFollowingSnapshot.code == 'S0.US', TrendFollowingSnapshot.trade_date == day,
            ).values(state=state))
    assert breadth.get_transitions('US', days=1)['items'] == []


def test_missing_neighbor_is_not_compared_to_older_stock_snapshot(source):
    seed_transitions(source)
    database, dates, _, _ = source
    with database.session_scope() as session:
        session.execute(delete(TrendFollowingSnapshot).where(
            TrendFollowingSnapshot.code == 'S0.US', TrendFollowingSnapshot.trade_date == dates[-2],
        ))
    assert breadth.get_transitions('US', days=1)['items'] == []


@pytest.mark.parametrize('days', [1, 3, 5])
def test_preview_window_uses_last_days_plus_one_snapshots(source, days):
    seed_transitions(source)
    _, dates, preview, sql = source
    preview.return_value = {**make_preview(), 'snapshots': [{'code': 'S0.US', 'state': 'CANDIDATE', 'rank': 8}]}
    official = breadth.get_transitions('US', days=days)
    mixed = breadth.get_transitions('US', days=days, include_preview=True)
    assert len(official['items']) == days
    assert len(mixed['items']) == days
    assert official['official_count'] == days
    assert mixed['official_count'] == days - 1
    assert mixed['items'][0]['is_preview'] is True
    assert mixed['items'][0]['previous_date'] == dates[-1]
    assert mixed['items'][0]['previous_state'] == 'BROKEN'
    assert mixed['items'][0]['current_state'] == 'CANDIDATE'
    assert mixed['items'][0]['rank_delta'] == -3
    assert mixed['items'][0]['trade_date'] == TODAY
    assert [row['trade_date'] for row in mixed['items']] == (
        [TODAY] if days == 1 else [TODAY, *dates[-(days - 1):][::-1]]
    )
    assert dates[-days] not in {row['trade_date'] for row in mixed['items']}
    assert all(row['is_preview'] is False for row in mixed['items'][1:])
    assert official['items'][0]['is_preview'] is False
    assert official['items'][0]['trade_date'] == dates[-1]
    assert [row['trade_date'] for row in official['items']] == dates[-days:][::-1]
    assert len(sql) >= 2


def test_priority_then_rank_and_limit(source):
    database, dates, _, _ = source
    with database.session_scope() as session:
        for code, before, after, rank in [('S0.US', 'WATCHING', 'CANDIDATE', 1),
                                         ('S1.US', 'TRENDING', 'WEAKENING', 8),
                                         ('S2.US', 'CANDIDATE', 'TRENDING', 3)]:
            for day, state in [(dates[-2], before), (dates[-1], after)]:
                session.execute(update(TrendFollowingSnapshot).where(
                    TrendFollowingSnapshot.code == code, TrendFollowingSnapshot.trade_date == day,
                ).values(state=state, rank=rank))
    assert [row['code'] for row in breadth.get_transitions('US', days=1, limit=2)['items']] == ['S2.US', 'S1.US']


def test_api_contract_validation_and_auth(source):
    app = FastAPI()
    app.include_router(endpoints.router, prefix='/trend')
    app.dependency_overrides[endpoints.require_current_user] = lambda: object()
    with TestClient(app) as client:
        for path in ['breadth-history', 'transitions']:
            response = client.get(f'/trend/{path}', params={'market': 'US'})
            assert response.status_code == 200, response.text
            assert client.get(f'/trend/{path}?market=HK').status_code == 422
            assert client.get(f'/trend/{path}?as_of=2099-01-01').status_code == 422
        for days in (1, 3, 5):
            assert client.get('/trend/transitions', params={'days': days}).status_code == 200
        for params in [{'days': 2}, {'days': 6}, {'limit': 21}, {'direction': 'neutral'}]:
            assert client.get('/trend/transitions', params=params).status_code == 422
        assert client.get('/trend/breadth-history?days=121').status_code == 422
        app.dependency_overrides.clear()
        assert client.get('/trend/breadth-history').status_code in (401, 403)


def test_transition_pairs_are_reachable_in_current_state_machine():
    from finance_analysis.trend_following.state import transition_state

    healthy = dict(reference_price=100, previous_low_10=80, ma20=90, ma20_slope=1,
                   ma10=95, trend_candidate=True, trend_score=80, rs_score=80, is_candidate=True)
    scenarios = [healthy, {**healthy, "reference_price": 70},
                 {**healthy, "trend_candidate": False, "is_candidate": False},
                 {**healthy, "is_candidate": False}]
    reachable = {(state, transition_state(row, {"state": state}).state)
                 for state in STATES for row in scenarios}
    assert set(breadth.TRANSITIONS) <= reachable
    assert set(breadth.VALID_STATES) == set(STATES)
    assert breadth.TRANSITIONS[("WEAKENING", "TRENDING")][0] == "strengthening"
    point = breadth.aggregate_point(TODAY, {"UNKNOWN": 1, "TRENDING": 1}, 2)
    assert point["coverage"] == 0.5 and point["warning"]
