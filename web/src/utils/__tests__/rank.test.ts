import { describe, expect, it } from 'vitest';
import { formatRank, rankPercentage } from '../rank';

describe('rank display', () => {
  it('expresses position within the full cohort and retains useful precision', () => {
    expect(formatRank(20, 500)).toBe('#20 · 前 4%');
    expect(formatRank(1, 5000)).toBe('#1 · 前 0.02%');
    expect(formatRank(1, 20000)).toBe('#1 · 前 <0.01%');
    expect(formatRank(1, 1)).toBe('#1 · 前 100%');
    expect(formatRank(2, 3)).toBe('#2 · 前 66.67%');
    expect(rankPercentage(20, 500)).toBe(4);
  });
  it('does not turn unknown totals or invalid ranks into fabricated percentages', () => {
    for (const total of [undefined, null, 0, -1, 10, NaN, Infinity, 20.5]) {
      expect(formatRank(20, total)).toBe('#20 · 百分比暂无');
    }
    for (const rank of [null, undefined, 0, -1, NaN, Infinity, 1.5]) expect(formatRank(rank, 100)).toBe('—');
  });
});
