import { describe, expect, it } from 'vitest';
import { positionMetrics, exitRows, scoreLabel } from '../stockStrategies';
import { adapt, type Detail } from '@/api/stockStrategies';
import { detail as raw } from '../../../e2e/fixtures/stockStrategies';
const detail = adapt<Detail>(raw);
describe('strategy display calculations', () => {
  it('uses account NAV for weight and position cost for floating return', () => {
    const pos = { ...detail.latest!.payload.positions['AAPL.US']!, stop: 198 };
    const metrics = positionMetrics(pos, 1100000);
    expect(metrics).toEqual({ value: 1100000, weight: 1, pnl: 100000, pnlPct: .1, stopDistance: .1 });
  });
  it('does not coerce missing values or invalid denominators to zero', () => {
    const pos = detail.latest!.payload.positions['AAPL.US']!;
    expect(positionMetrics({ ...pos, mark: NaN }, 0)).toEqual({ value: null, weight: null, pnl: null, pnlPct: null, stopDistance: null });
    expect(positionMetrics({ ...pos, entryPrice: 0, stop: -1 }, NaN)).toMatchObject({ weight: null, pnl: null, pnlPct: null, stopDistance: null });
  });
  it('merges pending exits without counting empty exit arrays as sales', () => {
    const day = structuredClone(detail.latest!);
    expect(exitRows(day)).toEqual([]);
    day.payload.positions['AAPL.US']!.pendingExit = ['卖出受阻'];
    day.payload.plan.exits['AAPL.US'] = ['卖出受阻', '收盘跌破MA20'];
    expect(exitRows(day)).toEqual([['AAPL.US', ['卖出受阻', '收盘跌破MA20']]]);
  });
  it('explains family-specific scores, including mixed stock and ETF scales', () => {
    const candidate = detail.latest!.payload.plan.candidates[0]!;
    expect(scoreLabel(detail.strategy, candidate)).toBe('MA20/MA50−1');
    expect(scoreLabel({ ...detail.strategy, family: 'hybrid' }, candidate)).toBe('Trend60');
    expect(scoreLabel({ ...detail.strategy, family: 'hybrid' }, { ...candidate, type: 'ETF' })).toContain('126日动量');
  });
});
