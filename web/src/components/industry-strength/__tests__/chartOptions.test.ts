import { describe, expect, it } from 'vitest';
import type { IndustrySnapshot } from '@/api/industryStrength';
import { heatmapCells, heatmapOption, matrixOption } from '../chartOptions';
import { bubbleSize } from '../display';

function row(overrides: Partial<IndustrySnapshot> = {}): IndustrySnapshot {
  return {
    tradeDate: '2026-09-16', industryCode: '881101.TI', industryName: '半导体', state: 'STRONG', close: 100,
    strengthRank: 1, strengthScore: 88, ret1D: 0.01, ret5D: 0.03, ret10D: 0.04, ret20D: 0.05,
    rs5D: 0.01, rs10D: 0.02, rs20D: 0.03, rankChange1D: 2, rankChange3D: 5, rankChange5D: null,
    previous5DReturn: 0.01, momentumAcceleration5D: 0.02, accelerationPercentile: 80, turnoverRatio5D: 1.5,
    upRatio: 0.7, aboveMa5Ratio: 0.8, aboveMa20Ratio: 0.9, equalWeightReturn: 0.01,
    constituentCount: 10, dailyValidCount: 10, ma5ValidCount: 10, aboveMa5Count: 8, ma20ValidCount: 10, aboveMa20Count: 9,
    upCount: 7, downCount: 2, flatCount: 1,
    dataTimestamp: '2026-09-16T07:00:00Z', membersObservedAt: '2026-09-16T11:00:00Z',
    createdAt: '2026-09-16T11:05:00Z', updatedAt: '2026-09-16T11:05:00Z',
    quality: { dailyBreadthCoverage: 1, ma5Coverage: 1, ma20Coverage: 1, catalogCount: 2, rankedCount: 10, coverage: 1, excluded: {} },
    ...overrides,
  };
}

describe('industry strength charts', () => {
  it('maps bubble size with the same formula used by the legend', () => {
    const option = matrixOption([row()], '881101.TI', 'light');
    const series = option.series[0] as { symbolSize: (value: number[]) => number };
    expect(series.symbolSize([88, 2, 1.5])).toBe(bubbleSize(1.5));
    expect(option.xAxis.name).toBe('综合强度');
    expect(option.yAxis.name).toContain('百分点');
  });

  it('keeps selected-day Top20 sample, missing style, and tooltip fields', () => {
    const leaders = [
      row(),
      row({ industryCode: '881102.TI', industryName: '银行', strengthRank: 2 }),
    ];
    const history = {
      dates: ['2026-09-15', '2026-09-16'],
      items: [row({ tradeDate: '2026-09-16' })],
    };
    const { cells, leaders: sample } = heatmapCells(leaders, history, '881101.TI', 'light');
    expect(sample.map((item) => item.industryCode)).toEqual(['881101.TI', '881102.TI']);
    const missing = cells.find((cell) => cell.code === '881102.TI' && cell.date === '2026-09-15');
    expect(missing?.missing).toBe(true);
    const present = cells.find((cell) => cell.code === '881101.TI' && cell.date === '2026-09-16');
    expect(present).toMatchObject({ rank: 1, rankedCount: 10, date: '2026-09-16', missing: false });
    const tooltip = heatmapOption(leaders, history, '881101.TI', 'light').tooltip.formatter;
    expect(tooltip({ data: present! })).toContain('半导体');
    expect(tooltip({ data: present! })).toContain('2026-09-16');
    expect(tooltip({ data: present! })).toContain('当日排名 1');
    expect(tooltip({ data: present! })).toContain('当日有效行业数 10');
    expect(tooltip({ data: missing! })).toContain('该日无该行业快照');
  });

  it('does not enlarge the sample when the selected industry is outside Top20', () => {
    const rows = Array.from({ length: 21 }, (_, index) => row({
      industryCode: `${index}.TI`,
      industryName: `行业${index}`,
      strengthRank: index + 1,
    }));
    const { leaders } = heatmapCells(rows, { dates: ['2026-09-16'], items: rows }, '20.TI', 'light');
    expect(leaders).toHaveLength(20);
    expect(leaders.some((item) => item.industryCode === '20.TI')).toBe(false);
  });
});
