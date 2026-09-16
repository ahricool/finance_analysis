import { describe, expect, it } from 'vitest';
import { describeTrendStateChange } from '../trendStateChange';

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
});
