import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.interfaces.api.v1.endpoints import market_data
from finance_analysis.interfaces.api.v1.schemas.intraday_options_stream import IntradayOptionsStream


def frame(tick=1, day='2026-11-25'):
    stamp = f'2026-11-26T02:00:{tick:02d}Z'
    return {
        'type': 'quotes', 'quotes': [], 'generated_at': stamp,
        'intraday_options': {
            'trading_date': day, 'market_status': 'closed', 'version': 'v1', 'generated_at': stamp,
            'items': [
                {'symbol': 'A.US', 'last_price': 10, 'result': {'score': 80, 'reasons': ['x' * 5000]}},
                {'symbol': 'B.US', 'last_price': 20},
            ],
            'simulation': {'states': [{'symbol': 'A.US', 'position': {'id': 't1'}}], 'trades': [],
                           'events': [{'id': 2, 'reason': 'x' * 5000}, {'id': 1}], 'statistics': []},
        },
    }


def apply(previous, wire):
    if 'intraday_options' in wire:
        return deepcopy(wire['intraday_options'])
    result = deepcopy(previous)
    for operation in wire['intraday_options_delta']['operations']:
        parent = result
        for part in operation['path'][:-1]:
            parent = parent[part]
        key = operation['path'][-1]
        if operation['op'] == 'remove':
            del parent[key]
        elif operation['op'] == 'insert':
            parent.insert(key, operation['value'])
        else:
            parent[key] = operation['value']
    result['generated_at'] = wire['generated_at']
    return result


def test_diff_preserves_full_snapshot_semantics_and_only_sends_changes():
    stream = IntradayOptionsStream()
    initial = frame()
    first = stream.encode(initial)
    assert first['intraday_options_revision'] == 1
    next_frame = frame(2)
    data = next_frame['intraday_options']
    data['items'][0]['last_price'] = 11
    data['items'][0]['result']['score'] = None
    data['items'].pop(1)
    data['items'].append({'symbol': 'C.US', 'last_price': 30})
    data['simulation']['states'][0].pop('position')
    data['simulation']['trades'].append({'id': 't1', 'exit_price': 11})
    data['simulation']['events'].insert(0, {'id': 3, 'reason': 'exit'})
    delta = stream.encode(next_frame)
    assert 'intraday_options' not in delta
    assert delta['intraday_options_delta']['base_revision'] == 1
    assert delta['intraday_options_delta']['revision'] == 2
    assert apply(first['intraday_options'], delta) == data
    assert len(json.dumps(delta)) < len(json.dumps(next_frame)) / 5
    assert 'x' * 5000 not in json.dumps(delta)
    heartbeat_frame = deepcopy(next_frame)
    heartbeat_frame['generated_at'] = heartbeat_frame['intraday_options']['generated_at'] = 'later'
    heartbeat = stream.encode(heartbeat_frame)
    assert heartbeat['intraday_options_delta']['operations'] == []
    assert len(json.dumps(heartbeat)) < 200
    assert apply(data, heartbeat) == heartbeat_frame['intraday_options']


def test_day_version_reorder_and_fresh_connection_reset():
    stream = IntradayOptionsStream()
    initial = frame()
    stream.encode(initial)
    reorder = frame(2)
    reorder['intraday_options']['items'].reverse()
    assert apply(initial['intraday_options'], stream.encode(reorder)) == reorder['intraday_options']
    day = frame(3, '2026-11-27')
    assert stream.encode(day)['intraday_options_revision'] == 3
    version = frame(4, '2026-11-27')
    version['intraday_options']['version'] = 'v2'
    assert stream.encode(version)['intraday_options_revision'] == 4
    assert IntradayOptionsStream().encode(version)['intraday_options_revision'] == 1


def test_unordered_database_rows_do_not_trigger_large_retransmissions():
    first = frame()
    simulation = first['intraday_options']['simulation']
    simulation['states'].append({'symbol': 'B.US', 'payload': 'x' * 5000})
    simulation['trades'] = [{'id': 'a', 'payload': 'x' * 5000}, {'id': 'b'}]
    second = deepcopy(first)
    second['intraday_options']['simulation']['states'].reverse()
    second['intraday_options']['simulation']['trades'].reverse()
    stream = IntradayOptionsStream()
    stream.encode(first)
    assert stream.encode(second)['intraday_options_delta']['operations'] == []


class Repository:
    closed = False

    async def close(self):
        self.closed = True


def setup_stream(monkeypatch):
    repo = Repository()
    calls = []

    async def snapshot(uid, repository, scope, market, tag_id, ungrouped, after_event_id):
        calls.append(after_event_id)
        return frame(len(calls))

    monkeypatch.setattr(market_data, '_live_snapshot', snapshot)
    monkeypatch.setattr(market_data.RealtimeStateRepository, 'from_url', lambda url: repo)
    monkeypatch.setattr(market_data, 'PUSH_INTERVAL_SECONDS', 0.001)
    monkeypatch.setattr(market_data, 'parse_session_uid', lambda token: 7)
    monkeypatch.setattr(market_data, '_user_exists', lambda uid: True)
    monkeypatch.setattr(market_data, 'get_effective_uid', lambda request: 7)
    return repo, calls


@pytest.mark.parametrize('delta', [True, False])
def test_websocket_negotiates_delta_and_preserves_legacy(monkeypatch, delta):
    repo, calls = setup_stream(monkeypatch)
    app = FastAPI()
    app.include_router(market_data.router)
    with TestClient(app) as client:
        with client.websocket_connect(f'/ws?scope=intraday-options&after_event_id=42&delta={str(delta).lower()}') as ws:
            first, second = ws.receive_json(), ws.receive_json()
            assert 'intraday_options' in first
            if delta:
                assert first['intraday_options_revision'] == 1
                assert second['intraday_options_delta']['operations'] == []
            else:
                assert 'intraday_options' in second
                assert 'intraday_options_revision' not in first
        with client.websocket_connect('/ws?scope=intraday-options&after_event_id=42&delta=true') as ws:
            assert ws.receive_json()['intraday_options_revision'] == 1
    assert all(cursor == 42 for cursor in calls)
    assert repo.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('delta', [True, False])
async def test_sse_uses_same_delta_protocol(monkeypatch, delta):
    repo, calls = setup_stream(monkeypatch)

    async def connected():
        return False

    response = await market_data.realtime_events(SimpleNamespace(is_disconnected=connected),
                                                 'intraday-options', 'US', after_event_id=42, delta=delta)
    iterator = response.body_iterator
    assert await anext(iterator) == ': connected\n\n'
    first = json.loads((await anext(iterator)).removeprefix('data: '))
    second = json.loads((await anext(iterator)).removeprefix('data: '))
    assert 'intraday_options' in first
    if delta:
        assert first['intraday_options_revision'] == 1
        assert second['intraday_options_delta']['operations'] == []
    else:
        assert 'intraday_options' in second
    await iterator.aclose()
    assert calls == [42, 42] and repo.closed
