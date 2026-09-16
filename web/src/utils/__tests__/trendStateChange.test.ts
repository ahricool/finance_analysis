import { describe, expect, it } from 'vitest';
import { describeTrendStateChange, TREND_TRANSITION_RANGES } from '../trendStateChange';

describe('describeTrendStateChange', () => {
  it.each([
    ['CANDIDATE', 'TRENDING', '新确认趋势'],
    ['WEAKENING', 'TRENDING', '趋势恢复'],
    ['IDLE', 'CANDIDATE', '新进入趋势候选'],
    ['WATCHING', 'CANDIDATE', '新进入趋势候选'],
    ['BROKEN', 'CANDIDATE', '重新形成趋势候选'],
    ['TRENDING', 'WEAKENING', '趋势开始弱化'],
    ['TRENDING', 'BROKEN', '趋势破坏'],
    ['WEAKENING', 'BROKEN', '趋势破坏'],
    ['CANDIDATE', 'BROKEN', '趋势破坏'],
    ['CANDIDATE', 'WEAKENING', '候选弱化'],
    ['IDLE', 'WATCHING', '状态变化'],
  ] as const)('%s → %s is %s', (previous, current, label) => {
    expect(describeTrendStateChange(previous, current)).toBe(label);
  });

  it('labels transition windows by change count, not snapshot count', () => {
    expect(TREND_TRANSITION_RANGES).toEqual([
      { days: 1, label: '今日变化' },
      { days: 3, label: '近3次变化' },
      { days: 5, label: '近5次变化' },
    ]);
  });
});
