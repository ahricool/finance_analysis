"""PR #514 review regressions: time order, branch projection and causal identity."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path

import pytest

from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.interfaces.api.v1.schemas.intraday_options import IntradayOptionsResponse
from finance_analysis.intraday_options.runtime import ranked_opportunity, read_snapshot, result_key
from finance_analysis.intraday_options.scoring import calculate, closed_session_bars
from finance_analysis.intraday_options.simulation import transition
from finance_analysis.intraday_options.rules import entry_interval
from tests.intraday_options.test_continuation import continuation, path
from tests.intraday_options.test_scoring import score
from tests.intraday_options.test_structure import prices
from tests.intraday_options.test_simulation import quote
from tests.market_stream.fakes import FakeRedis


@pytest.mark.parametrize('side', [1, -1])
@pytest.mark.parametrize('moves_out', [False, True])
def test_entry_waits_for_post_confirmation_quote_and_rechecks_live_price(side, moves_out):
    bars = path(side)
    confirmed = bars[-1].bar_time + timedelta(minutes=1)
    now = confirmed + timedelta(seconds=5)
    r = calculate('SPY.US', bars, now)
    b = continuation(r)
    assert b['confirmed_at'] == confirmed.isoformat()
    price = sum(entry_interval(b)) / 2
    early = replace(quote(confirmed - timedelta(seconds=10), price), received_at=now)
    state, events = transition({}, 'SPY.US', r, early, now)
    assert not state.get('position')
    assert not any(e['kind'] == 'entry' for e in events)
    assert state['plans'][0]['execution_reason'] == '等待确认后的有效报价'
    assert b['status'] == 'confirmed'
    when = now + timedelta(seconds=5)
    new_price = b['trigger'] + side * 1.1 * b['atr'] if moves_out else price
    fresh = replace(quote(when - timedelta(seconds=2), new_price), received_at=when)
    state, events = transition(state, 'SPY.US', r, fresh, when)
    if moves_out:
        assert not state.get('position')
        assert '不在冻结执行区间' in state['plans'][0]['execution_reason']
    else:
        assert state['position']['entry_price_at'] == fresh.event_time.isoformat()
        assert state['position']['entry_price'] == new_price
        assert sum(e['kind'] == 'entry' for e in events) == 1
        # A new branch's later confirmation must never veto an existing position's exit.
        later = when + timedelta(seconds=5)
        r['opportunities']['branches'][0]['confirmed_at'] = later.isoformat()
        exit_quote = quote(later - timedelta(seconds=1), state['position']['invalidation'] - side * .01)
        state, events = transition(state, 'SPY.US', r, exit_quote, later)
        assert not state['position'] and sum(e['kind'] == 'exit' for e in events) == 1


def multi_branch_result(side=1):
    bars = path(side)
    now = bars[-1].bar_time + timedelta(minutes=1, seconds=5)
    r = calculate('SPY.US', bars, now)
    b = continuation(r)
    b['quality_score'] = 75
    a = {**deepcopy(b), 'kind': 'trend_recovery', 'structure_id': 'A', 'process_id': 'A',
         'direction': 'bearish' if side == 1 else 'bullish', 'trigger': 110 if side == 1 else 90,
         'invalidation': 111 if side == 1 else 89, 'quality_score': 99}
    a['entry_low'], a['entry_high'] = entry_interval(a)
    a['max_risk_atr'] = None
    r['opportunities'].update(primary=a, branches=[a, b])
    return r, b, now


@pytest.mark.parametrize('side', [1, -1])
def test_executed_valid_branch_drives_api_ranking_not_highest_shape(side):
    async def run():
        repo = RealtimeStateRepository(FakeRedis())
        r, b, now = multi_branch_result(side)
        q = quote(now, sum(entry_interval(b)) / 2)
        state, _ = transition({}, 'SPY.US', r, q, now)
        assert state['position']['opportunity_id'] == b['structure_id']
        assert not state['plans'][0]['opportunity_valid']
        assert state['plans'][1]['opportunity_valid'] and not state['plans'][1]['executable']
        await repo.write_quote(q)
        await repo.redis.set(result_key('SPY.US'), json.dumps(r))
        await repo.redis.set('rt:intraday-simulation:SPY.US', json.dumps(state))
        row = (await read_snapshot(repo, {}, now))['items'][0]
        assert row['opportunity_eligible']
        ranked = row['ranked_opportunity']
        assert ranked['structure_id'] == b['structure_id']
        assert ranked['quality_score'] == 75 and ranked['direction'] == b['direction']
        assert '已模拟持有' in ranked['execution_reason']
        assert row['result']['opportunities']['primary']['structure_id'] == 'A'
        parsed = IntradayOptionsResponse.model_validate(await read_snapshot(repo, {}, now))
        assert parsed.items[0].ranked_opportunity.structure_id == b['structure_id']
        if side == -1:
            # Shared with the actual Vue table regression, not a second hand-written contract.
            expected = json.loads((Path(__file__).parent / 'fixtures/ranked_opportunity.json').read_text())
            serialized = parsed.items[0].model_dump(mode='json')
            assert {
                'opportunity_eligible': serialized['opportunity_eligible'],
                'ranked_opportunity': {k: serialized['ranked_opportunity'][k] for k in expected['ranked_opportunity']},
                'primary': {k: serialized['result']['opportunities']['primary'][k] for k in expected['primary']},
                'position': {k: serialized['simulation']['position'][k] for k in expected['position']},
            } == expected
        for change in ('invalid', 'as_of', 'revision', 'stale', 'cutoff', 'version'):
            altered = deepcopy(state)
            check_at = now
            if change == 'invalid':
                for p in altered['plans']:
                    p['opportunity_valid'] = False
            elif change == 'as_of':
                altered['plans'][1]['minute_as_of'] = (now - timedelta(minutes=1)).isoformat()
            elif change == 'revision':
                altered['plans'][1]['trigger'] += 1
            elif change == 'stale':
                check_at += timedelta(seconds=31)
            elif change == 'version':
                altered['plans'][1]['rule_version'] = 'underlying_sim_v3'
            else:
                altered['cutoff'] = now.isoformat()
            await repo.redis.set('rt:intraday-simulation:SPY.US', json.dumps(altered))
            row = (await read_snapshot(repo, {}, check_at))['items'][0]
            assert not row['opportunity_eligible'] and row['ranked_opportunity'] is None, change
    asyncio.run(run())


@pytest.mark.parametrize('reverse', [False, True])
def test_ranking_prefers_actual_entry_then_uses_stable_quality_order(reverse):
    r, b, now = multi_branch_result()
    a = {**deepcopy(b), 'structure_id': 'A', 'process_id': 'already_traded', 'quality_score': 99}
    r['opportunities'].update(primary=a, branches=[a, b] if reverse else [b, a])
    previous = {'trading_date': r['trading_date'], 'used_processes': ['already_traded']}
    state, _ = transition(previous, 'SPY.US', r, quote(now, sum(entry_interval(b)) / 2), now)
    # A is valid for display but consumed for trading; B is the actual new entry.
    assert all(p['opportunity_valid'] for p in state['plans'])
    assert state['position']['opportunity_id'] == b['structure_id']
    assert ranked_opportunity(r, state, now)['structure_id'] == b['structure_id']
    state['entered_opportunity_id'] = None
    assert ranked_opportunity(r, state, now)['structure_id'] == 'A'
    # With no consumed processes, execution uses the same order regardless of input order.
    state, _ = transition({}, 'SPY.US', r, quote(now, sum(entry_interval(b)) / 2), now)
    assert state['position']['opportunity_id'] == 'A'


@pytest.mark.parametrize('side', [1, -1])
def test_recovery_identity_cannot_borrow_distant_pause_that_slides_out_next_minute(side):
    values = [100, 100.4, 100.8, 100.75] + [100.75 + .1 * i for i in range(1, 56)]
    values += [values[-1] - .8, values[-1] - .75]
    bars = [replace(b, high=max(b.open, b.close) + Decimal('.3'), low=min(b.open, b.close) - Decimal('.3'))
            for b in prices([100 + side * (v - 100) for v in values])]
    first = next(b for b in score(bars[:60])['opportunities']['branches'] if b['kind'] == 'trend_recovery')
    second = next(b for b in score(bars)['opportunities']['branches'] if b['structure_id'] == first['structure_id'])
    assert first['structure_start'] == bars[59].bar_time.isoformat()
    keys = ('structure_id', 'process_id', 'structure_start', 'structure_end', 'structure_high', 'structure_low',
            'trigger', 'invalidation', 'atr')
    assert {k: first[k] for k in keys} == {k: second[k] for k in keys}
    assert score(deepcopy(bars)) == score(bars)  # Restart replay has no hidden anchor state.


@pytest.mark.parametrize('original_available', [False, True])
def test_minute_selection_excludes_unreceived_versions_before_deduplicating(original_available):
    bars = path()
    original = bars[-1]
    now = original.bar_time + timedelta(minutes=1, seconds=5)
    revised = replace(original, high=original.high + 1, received_at=now + timedelta(seconds=10))
    available = bars if original_available else bars[:-1]
    inputs = [*available, revised]
    selected = closed_session_bars('SPY.US', inputs, now)
    assert selected == available
    assert closed_session_bars('SPY.US', list(reversed(inputs)), now) == available
    assert calculate('SPY.US', inputs, now) == calculate('SPY.US', available, now)
    after = revised.received_at
    assert closed_session_bars('SPY.US', inputs, after)[-1] == revised
    assert calculate('SPY.US', inputs, after) != calculate('SPY.US', available, after)
    if original_available:
        r = calculate('SPY.US', inputs, now)
        state, _ = transition({}, 'SPY.US', r, quote(now, 104), now)
        frozen = deepcopy(state['position'])
        changed = calculate('SPY.US', inputs, after)
        state, _ = transition(state, 'SPY.US', changed, quote(after, 104), after)
        assert state['position']['evidence'] == frozen['evidence']
        assert state['position']['entry_evidence'] == frozen['entry_evidence']
        assert state['confirmations'][frozen['opportunity_id']] == frozen['evidence']
